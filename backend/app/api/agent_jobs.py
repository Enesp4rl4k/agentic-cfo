"""
Agent Jobs API — /api/v1/agent-jobs/*

POST /agent-jobs/{agent_type}         → Enqueue async job
GET  /agent-jobs/{job_id}             → Get job status + result
GET  /agent-jobs/list/{agent_type}    → List recent jobs for agent+org
DELETE /agent-jobs/{job_id}           → Cancel / delete job

Desteklenen agent tipleri: cto, cmo, coo, chro, risk, audit, compliance

Pattern: request gelir → AgentJob kaydı oluşturulur (PENDING) →
asyncio.create_task() ile pipeline arka planda çalışır →
Frontend /status'u poll eder → COMPLETED/FAILED döner.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.run_ledger import agent_run
from app.api.auth import get_current_user, require_role
from app.config import get_settings
from app.database import get_db
from app.models.agent_job import AGENT_TYPES, AgentJob, AgentJobStatus
from app.models.user import User, UserRole
from app.platform.run_gate import evaluate

router = APIRouter()
logger = logging.getLogger(__name__)


def _jsonable(value: Any) -> Any:
    """Recursively coerce pipeline output into JSON-safe primitives.

    Agent states carry @dataclass entries (e.g. CTOStepLog) and enums that the
    JSON columns cannot serialize — writing them raw raises TypeError mid-commit
    and the job stays RUNNING forever.
    """
    import dataclasses
    from enum import Enum

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _jsonable(dataclasses.asdict(value))
    if isinstance(value, Enum):
        return _jsonable(value.value)
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(v) for v in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "model_dump"):  # pydantic v2 model
        return _jsonable(value.model_dump())
    return str(value)


# ── Request schemas ────────────────────────────────────────────────────────────

class AgentJobRequest(BaseModel):
    """Universal request — each agent uses only the fields it needs."""
    company_name: str | None = None
    reporting_period: str | None = None

    # CTO
    cloud_billing_csv: str | None = None
    git_log_text: str | None = None
    incident_csv: str | None = None
    sprint_csv: str | None = None

    # CMO
    campaign_csv: str | None = None
    funnel_csv: str | None = None
    cohort_csv: str | None = None

    # COO
    process_csv: str | None = None
    resource_csv: str | None = None
    sla_csv: str | None = None

    # CHRO
    headcount_csv: str | None = None
    attrition_csv: str | None = None
    compensation_csv: str | None = None

    # Risk
    register_csv: str | None = None
    loss_csv: str | None = None
    kri_csv: str | None = None

    # Audit
    findings_csv: str | None = None
    controls_csv: str | None = None
    audit_plan_csv: str | None = None

    # Compliance
    policies_csv: str | None = None
    violations_csv: str | None = None
    regulations_csv: str | None = None


# ── Helpers ────────────────────────────────────────────────────────────────────

def _require_org(user: User) -> str:
    if not user.org_id:
        raise HTTPException(400, "Organizasyona üye değilsiniz.")
    return user.org_id


def _job_dict(job: AgentJob) -> dict[str, Any]:
    return {
        "id":           job.id,
        "agent_type":   job.agent_type,
        "status":       job.status,
        "progress":     job.progress,
        "result":       job.result_json,
        "gate":         (job.result_json or {}).get("gate"),
        "logs":         job.logs,
        "error":        job.error_message,
        "created_at":   job.created_at.isoformat(),
        "updated_at":   job.updated_at.isoformat(),
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }


async def _run_agent_pipeline(job_id: str, agent_type: str, input_data: dict) -> None:
    """
    Fire-and-forget background task.
    Opens its own DB session — never shares the request session.
    """
    from app.database import engine, get_session_factory

    async with get_session_factory(engine())() as db:
        # Atomic claim: however many times this is delivered, one run happens.
        claimed = await db.execute(
            update(AgentJob)
            .where(AgentJob.id == job_id, AgentJob.status == AgentJobStatus.PENDING)
            .values(
                status=AgentJobStatus.RUNNING,
                progress=10,
                lease_expires_at=datetime.now(UTC) + timedelta(seconds=get_settings().job_lease_seconds),
            )
            .execution_options(synchronize_session=False)
        )
        await db.commit()
        if claimed.rowcount != 1:
            logger.warning("AgentJob %s not claimable; skipping", job_id)
            return
        job = await db.get(AgentJob, job_id)
        if not job:  # pragma: no cover - deleted between the claim and this read
            return
        await db.refresh(job)

        try:
            async with agent_run(db, pipeline=agent_type, org_id=job.org_id, job_id=job_id) as run:
                result = await _dispatch_pipeline(agent_type, job_id, input_data)

                gate = evaluate(result)
                job.progress = 100
                job.lease_expires_at = None
                job.result_json = {**_jsonable(result), "gate": gate.to_dict()}
                job.logs = _jsonable(result.get("logs", []))
                if gate.awaiting_review:
                    job.status = AgentJobStatus.AWAITING_REVIEW
                    run.row.status = "awaiting_review"
                else:
                    job.status = AgentJobStatus.COMPLETED
                    job.completed_at = datetime.now(UTC)
            if gate.awaiting_review:
                logger.info("AgentJob %s (%s) held: %s", job_id, agent_type, gate.reasons)
                return
            logger.info("AgentJob %s (%s) completed", job_id, agent_type)

            if job.org_id:
                try:
                    from app.agents.orchestration.auto_chain import on_agent_complete
                    from app.services.context_persist import persist_agent_completion

                    await persist_agent_completion(
                        str(job.org_id),
                        agent_type,
                        result,
                        db,
                        job_id=job_id,
                        company_name=input_data.get("company_name"),
                        reporting_period=input_data.get("reporting_period"),
                        auto_chain_hook=on_agent_complete,
                        approved=True,   # passed the gate above
                    )
                except Exception as persist_exc:
                    logger.warning(
                        "AgentJob %s context persist failed: %s", job_id, persist_exc
                    )

        except Exception as exc:
            logger.error("AgentJob %s (%s) failed: %s", job_id, agent_type, exc, exc_info=True)
            # The failed commit left the session in a rolled-back state — clear
            # it first or the FAILED status write below raises PendingRollbackError
            # and the job stays RUNNING forever.
            await db.rollback()
            job.status = AgentJobStatus.FAILED
            job.progress = 0
            job.lease_expires_at = None
            job.error_message = str(exc)[:1000]
            job.completed_at = datetime.now(UTC)
            await db.commit()


async def _dispatch_pipeline(
    agent_type: str, job_id: str, data: dict
) -> dict[str, Any]:
    """Route to the correct pipeline function."""

    if agent_type == "cto":
        from app.agents.cto.orchestrator import run_cto_pipeline
        state = await run_cto_pipeline(
            job_id=job_id,
            cloud_billing_csv=data.get("cloud_billing_csv"),
            git_log_text=data.get("git_log_text"),
            incident_csv=data.get("incident_csv"),
            sprint_csv=data.get("sprint_csv"),
            company_name=data.get("company_name"),
        )
        return dict(state)

    elif agent_type == "cmo":
        from app.agents.cmo.orchestrator import run_cmo_pipeline
        state = await run_cmo_pipeline(
            job_id=job_id,
            company_name=data.get("company_name"),
            period=data.get("reporting_period"),
            campaign_csv=data.get("campaign_csv"),
            funnel_csv=data.get("funnel_csv"),
            cohort_csv=data.get("cohort_csv"),
        )
        return dict(state)

    elif agent_type == "coo":
        from app.agents.coo.orchestrator import run_coo_pipeline
        state = await run_coo_pipeline(
            job_id=job_id,
            company_name=data.get("company_name"),
            period=data.get("reporting_period"),
            process_csv=data.get("process_csv"),
            resource_csv=data.get("resource_csv"),
            sla_csv=data.get("sla_csv"),
        )
        return dict(state)

    elif agent_type == "chro":
        from app.agents.chro.orchestrator import run_chro_pipeline
        state = await run_chro_pipeline(
            headcount_csv=data.get("headcount_csv", ""),
            attrition_csv=data.get("attrition_csv", ""),
            compensation_csv=data.get("compensation_csv", ""),
            company_name=data.get("company_name"),
            analysis_period=data.get("reporting_period"),
        )
        return dict(state)

    elif agent_type == "risk":
        from app.agents.risk.orchestrator import run_risk_pipeline
        state = await run_risk_pipeline(
            register_csv=data.get("register_csv", ""),
            loss_csv=data.get("loss_csv", ""),
            kri_csv=data.get("kri_csv", ""),
            company_name=data.get("company_name"),
            reporting_period=data.get("reporting_period"),
        )
        return dict(state)

    elif agent_type == "audit":
        from app.agents.audit.orchestrator import run_audit_pipeline
        # The request's names are kept; the pipeline's are coverage_csv and
        # audit_period (passing the request's raised TypeError on every job).
        state = await run_audit_pipeline(
            findings_csv=data.get("findings_csv") or "",
            controls_csv=data.get("controls_csv") or "",
            coverage_csv=data.get("audit_plan_csv") or "",
            company_name=data.get("company_name"),
            audit_period=data.get("reporting_period"),
        )
        return dict(state)

    elif agent_type == "compliance":
        from app.agents.compliance.orchestrator import run_compliance_pipeline
        state = await run_compliance_pipeline(
            job_id=job_id,
            policy_csv=data.get("policies_csv"),
            violations_csv=data.get("violations_csv"),
            regulations_csv=data.get("regulations_csv"),
            company_name=data.get("company_name"),
            audit_period=data.get("reporting_period"),
        )
        return dict(state)

    else:
        raise ValueError(f"Unknown agent type: {agent_type}")


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post("/agent-jobs/{agent_type}", status_code=202)
async def enqueue_agent_job(
    agent_type: str,
    body: AgentJobRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Enqueue an async agent job. Returns immediately with job_id.
    Poll GET /agent-jobs/{job_id} for status.
    """
    if agent_type not in AGENT_TYPES:
        raise HTTPException(
            400,
            detail=f"Unknown agent type '{agent_type}'. Valid: {sorted(AGENT_TYPES)}",
        )

    org_id = _require_org(current_user)

    # Build input_data from request body
    input_data = body.model_dump(exclude_none=True)

    # Create job record
    job = AgentJob(
        agent_type=agent_type,
        user_id=current_user.id,
        org_id=org_id,
        status=AgentJobStatus.PENDING,
        input_data=input_data,
        progress=0,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    job_id = job.id

    # Fire-and-forget — does not block the response
    from app.core.background import spawn

    spawn(_run_agent_pipeline(job_id, agent_type, input_data), name=f"agent-job-{job_id}")

    logger.info("AgentJob %s (%s) enqueued for org=%s", job_id, agent_type, org_id)

    return {
        "data": {
            "job_id":     job_id,
            "agent_type": agent_type,
            "status":     AgentJobStatus.PENDING,
            "message":    f"{agent_type.upper()} analizi başlatıldı. job_id ile durumu takip edin.",
        },
        "error": None,
    }


@router.get("/agent-jobs/review-queue")
async def review_queue(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Results of this organisation waiting for its owner's decision, oldest first."""
    org_id = _require_org(user)
    rows = (await db.execute(
        select(AgentJob)
        .where(AgentJob.org_id == org_id, AgentJob.status == AgentJobStatus.AWAITING_REVIEW)
        .order_by(AgentJob.created_at)
    )).scalars().all()
    return {"data": [_job_dict(j) for j in rows], "error": None}


async def _close_review(
    db: AsyncSession, job: AgentJob, status: str, review: dict[str, Any], error: str | None = None
) -> bool:
    """Atomic on the status: of two people deciding at once, one wins."""
    now = datetime.now(UTC)
    won = await db.execute(
        update(AgentJob)
        .where(AgentJob.id == job.id, AgentJob.status == AgentJobStatus.AWAITING_REVIEW)
        .values(
            status=status,
            completed_at=now,
            error_message=error,
            result_json={**(job.result_json or {}), "review": {**review, "at": now.isoformat()}},
        )
        .execution_options(synchronize_session=False)
    )
    await db.commit()
    return bool(won.rowcount == 1)


async def approve_held_job(db: AsyncSession, job: AgentJob, approved_by: str) -> bool:
    """Release a held result into the company's context. False if already decided."""
    from app.agents.orchestration import auto_chain
    from app.services.context_persist import persist_agent_completion

    if not await _close_review(db, job, AgentJobStatus.COMPLETED, {"approved_by": approved_by}):
        return False
    await db.refresh(job)
    inputs = job.input_data or {}
    await persist_agent_completion(
        str(job.org_id), job.agent_type, dict(job.result_json or {}), db,
        job_id=job.id,
        company_name=inputs.get("company_name"),
        reporting_period=inputs.get("reporting_period"),
        auto_chain_hook=auto_chain.on_agent_complete,
        approved=True,
    )
    return True


async def _held_job_of_org(db: AsyncSession, job_id: str, user: User) -> AgentJob:
    job = await db.get(AgentJob, job_id)
    if not job or job.org_id != _require_org(user):
        raise HTTPException(404, "Job bulunamadı.")
    return job


@router.post(
    "/agent-jobs/{job_id}/approve",
    responses={
        403: {"description": "Only the organisation's owner decides."},
        404: {"description": "Job not found."},
        409: {"description": "Not waiting for review, or already decided."},
    },
)
async def approve_agent_job(
    job_id: str,
    user: User = Depends(require_role(UserRole.OWNER)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """The owner accepts a held result: it reaches the context and the chain runs."""
    job = await _held_job_of_org(db, job_id, user)
    if not await approve_held_job(db, job, str(user.id)):
        raise HTTPException(409, "Bu sonuç onay beklemiyor.")
    return {"data": {"job_id": job_id, "approved": True}, "error": None}


@router.post(
    "/agent-jobs/{job_id}/reject",
    responses={
        403: {"description": "Only the organisation's owner decides."},
        404: {"description": "Job not found."},
        409: {"description": "Not waiting for review, or already decided."},
    },
)
async def reject_agent_job(
    job_id: str,
    user: User = Depends(require_role(UserRole.OWNER)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """The owner refuses a held result: it stays on record, out of the context."""
    job = await _held_job_of_org(db, job_id, user)
    if not await _close_review(
        db, job, AgentJobStatus.FAILED, {"rejected_by": str(user.id)},
        error="Sahibi tarafından reddedildi.",
    ):
        raise HTTPException(409, "Bu sonuç onay beklemiyor.")
    return {"data": {"job_id": job_id, "approved": False}, "error": None}


@router.get("/agent-jobs/{job_id}")
async def get_agent_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Poll for job status and result."""
    org_id = _require_org(current_user)

    job = await db.get(AgentJob, job_id)
    if not job or job.org_id != org_id:
        raise HTTPException(404, "Job bulunamadı.")

    return {"data": _job_dict(job), "error": None}


@router.get("/agent-jobs/list/{agent_type}")
async def list_agent_jobs(
    agent_type: str,
    limit: int = Query(10, le=50),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List recent jobs for a given agent type within the current org."""
    if agent_type not in AGENT_TYPES:
        raise HTTPException(400, f"Unknown agent type '{agent_type}'.")

    org_id = _require_org(current_user)

    result = await db.execute(
        select(AgentJob)
        .where(AgentJob.org_id == org_id, AgentJob.agent_type == agent_type)
        .order_by(desc(AgentJob.created_at))
        .limit(limit)
    )
    jobs = result.scalars().all()

    return {
        "data": {
            "jobs":  [_job_dict(j) for j in jobs],
            "total": len(jobs),
        },
        "error": None,
    }


@router.delete("/agent-jobs/{job_id}", status_code=204)
async def delete_agent_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a completed or failed job record."""
    org_id = _require_org(current_user)

    job = await db.get(AgentJob, job_id)
    if not job or job.org_id != org_id:
        raise HTTPException(404, "Job bulunamadı.")

    if job.status == AgentJobStatus.RUNNING:
        raise HTTPException(409, "Çalışan job silinemez. Tamamlanmasını bekleyin.")

    await db.delete(job)
    await db.commit()
