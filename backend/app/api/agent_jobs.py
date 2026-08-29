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

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.models.agent_job import AGENT_TYPES, AgentJob, AgentJobStatus
from app.models.user import User

router = APIRouter()
logger = logging.getLogger(__name__)


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
        job = await db.get(AgentJob, job_id)
        if not job:
            logger.error("AgentJob %s not found in background task", job_id)
            return

        job.status = AgentJobStatus.RUNNING
        job.progress = 10
        await db.commit()

        try:
            result = await _dispatch_pipeline(agent_type, job_id, input_data)

            job.status = AgentJobStatus.COMPLETED
            job.progress = 100
            job.result_json = result
            job.logs = result.get("logs", [])
            job.completed_at = datetime.now(UTC)
            await db.commit()
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
                    )
                except Exception as persist_exc:
                    logger.warning(
                        "AgentJob %s context persist failed: %s", job_id, persist_exc
                    )

        except Exception as exc:
            logger.error("AgentJob %s (%s) failed: %s", job_id, agent_type, exc, exc_info=True)
            job.status = AgentJobStatus.FAILED
            job.progress = 0
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
        state = await run_audit_pipeline(
            findings_csv=data.get("findings_csv", ""),
            controls_csv=data.get("controls_csv", ""),
            audit_plan_csv=data.get("audit_plan_csv", ""),
            company_name=data.get("company_name"),
            reporting_period=data.get("reporting_period"),
        )
        return dict(state)

    elif agent_type == "compliance":
        from app.agents.compliance.orchestrator import run_compliance_pipeline
        state = await run_compliance_pipeline(
            policies_csv=data.get("policies_csv", ""),
            violations_csv=data.get("violations_csv", ""),
            regulations_csv=data.get("regulations_csv", ""),
            company_name=data.get("company_name"),
            reporting_period=data.get("reporting_period"),
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
    asyncio.create_task(
        _run_agent_pipeline(job_id, agent_type, input_data),
        name=f"agent-job-{job_id}",
    )

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
