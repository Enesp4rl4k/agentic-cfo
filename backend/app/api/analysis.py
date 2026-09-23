from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.transaction import Transaction
from app.models.user import User

router = APIRouter()


def _check_job_access(job: AnalysisJob, user: User) -> None:
    """Raise 404 unless the user owns this job.

    Delegates to `app.api.access`. The old test skipped itself when either
    side had no organisation — a user without one reached every job.
    """
    from app.api.access import ensure_tenant

    ensure_tenant(user, org_id=job.org_id, user_id=job.user_id)


class AnalyzeRequest(BaseModel):
    """Optional request body for POST /analyze/{job_id}."""
    budget_input: dict[str, Any] | None = None


@router.post("/analyze/{job_id}")
async def start_analysis(
    job_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    body: AnalyzeRequest | None = None,
) -> dict:
    """
    Trigger CFO analysis pipeline for an uploaded job.
    Job is enqueued into Redis via ARQ — survives application restarts.

    Optionally provide budget_input for budget vs actual comparison:
    {
      "budget_input": {
        "items": [{"category": "salary", "budgeted": 500000}],
        "period": "2024-01"
      }
    }

    Duplicate protection is two-layered (DDIA Ch.11):
      - `Idempotency-Key` (optional) dedupes the *dispatch* within an hour —
        a retried HTTP request that got a network error does not enqueue twice.
      - The worker's atomic claim dedupes the *work*: even without the header
        (double-click, two tabs), exactly one delivery runs the pipeline.
    """
    from app.worker import enqueue_analysis

    job = await db.get(AnalysisJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    _check_job_access(job, current_user)
    if job.status not in (JobStatus.PENDING, JobStatus.FAILED):
        raise HTTPException(
            status_code=409,
            detail=f"Job is already in status '{job.status}'. Cannot re-run.",
        )

    idem_key = request.headers.get("Idempotency-Key")
    if idem_key:
        deduplicated = await _idempotency_seized(str(current_user.id), idem_key)
        if deduplicated:
            return {
                "data": {"job_id": job_id, "status": "queued", "deduplicated": True},
                "error": None,
            }

    budget_input = body.budget_input if body else None
    await enqueue_analysis(job_id, budget_input)

    return {"data": {"job_id": job_id, "status": "queued"}, "error": None}


async def _idempotency_seized(user_id: str, key: str) -> bool:
    """True when this Idempotency-Key was already used (within the TTL).

    Redis NX is the fast path; with no broker the answer is False — the
    worker's claim still guarantees the work runs once, only the *dispatch*
    may repeat.
    """
    from app.core.redis_client import get_redis, mark_unavailable

    r = await get_redis()
    if r is None:
        return False
    try:
        acquired = await r.set(
            f"idem:analysis:{user_id}:{key[:128]}",
            "1",
            ex=3600,
            nx=True,
        )
    except Exception as exc:
        mark_unavailable(exc)
        return False
    return not bool(acquired)


@router.get("/analysis/{job_id}")
async def get_analysis_status(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Poll job status and get logs."""
    job = await db.get(AnalysisJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    _check_job_access(job, current_user)
    return {
        "data": {
            "job_id": job.id,
            "status": job.status,
            "filename": job.filename,
            "awaiting_review": job.awaiting_review,
            "min_confidence": float(job.min_confidence) if job.min_confidence else None,
            "logs": job.logs or [],
            "error": job.error_message,
            "created_at": job.created_at.isoformat(),
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        },
        "error": None,
    }


@router.post("/analysis/{job_id}/approve")
async def approve_review(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Human approval of a result held by the confidence gate.

    The analysis already ran and its results are saved; what the gate held back
    is everything that acts on them — company context, the command center's
    snapshot, the auto-chain. Approval marks the job completed, records who
    approved it, and runs that held step from the saved results.

    It used to set the job back to PENDING and nothing else: nothing re-ran
    it, so an approved analysis sat "pending" forever and never reached the
    command center.
    """
    job = await db.get(AnalysisJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    _check_job_access(job, current_user)
    if not job.awaiting_review:
        raise HTTPException(status_code=409, detail="Job is not awaiting review.")
    now = datetime.now(UTC)
    meta = dict(job.result_metadata or {})
    # `devam` is the durable record that the held continuation is owed; it is
    # set in the same UPDATE that completes the job and cleared to "tamam" by
    # the continuation (app.services.review_continuation).
    meta["review"] = {"approved_by": current_user.id, "approved_at": now.isoformat(),
                      "devam": "bekliyor"}
    # Atomic on the flag, not on the read: two simultaneous approvers both saw
    # `awaiting_review=True`, but only one UPDATE flips it — the second gets
    # rowcount 0 and a 409 instead of two "approved" responses and the held
    # continuation running twice.
    stmt = (
        update(AnalysisJob)
        .where(AnalysisJob.id == job_id, AnalysisJob.awaiting_review.is_(True))
        .values(
            awaiting_review=False,
            status=JobStatus.COMPLETED,
            updated_at=now,
            result_metadata=meta,
        )
        .execution_options(synchronize_session=False)
    )
    result = await db.execute(stmt)
    await db.commit()
    if result.rowcount != 1:
        raise HTTPException(status_code=409, detail="Job is not awaiting review.")

    if job.org_id:
        # Off the request (it reruns the semantic snapshot and the chain, ~20s
        # in a live run) and durable: queued under a per-job id, recovered by
        # the reaper if it never reports done.
        from app.services.review_continuation import devami_baslat

        await devami_baslat(job_id)
    return {"data": {"job_id": job_id, "approved": True, "status": JobStatus.COMPLETED.value}, "error": None}


@router.get("/analysis/{job_id}/decision-packet")
async def get_decision_packet(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """The review moment in one response: situation, options with their
    computed consequences, real data freshness, and this org's precedent.

    Deterministic and read-only — no LLM in the path, so it cannot
    hallucinate a number the manager is about to act on, and it is safe
    to call repeatedly while they keep thinking. A job still mid-run →
    409: there is nothing to decide yet.
    """
    job = await db.get(AnalysisJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    _check_job_access(job, current_user)

    from app.services.decision_packet import RUNNING_STATUSES, build_decision_packet

    if str(job.status) in RUNNING_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=(
                "Analiz henüz tamamlanmadı — karar paketi sonuçlar "
                "hazır olduğunda oluşur."
            ),
        )

    packet = await build_decision_packet(db, job)
    return {"data": packet, "error": None}


@router.get("/jobs")
async def list_jobs(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = 20,
) -> dict:
    """List the most recent analysis jobs for the current org."""
    q = select(AnalysisJob).order_by(desc(AnalysisJob.created_at)).limit(limit)
    # Scoped to the org — and, for a user without one, to their own jobs.
    # The filter used to be skipped instead, listing every organisation's.
    if current_user.org_id:
        q = q.where(AnalysisJob.org_id == current_user.org_id)
    else:
        q = q.where(AnalysisJob.user_id == current_user.id)
    result = await db.execute(q)
    jobs = result.scalars().all()
    return {
        "data": [
            {
                "job_id": j.id,
                "status": j.status,
                "filename": j.filename,
                "created_at": j.created_at.isoformat(),
                "completed_at": j.completed_at.isoformat() if j.completed_at else None,
            }
            for j in jobs
        ],
        "error": None,
    }


@router.get("/analysis/{job_id}/transactions")
async def list_transactions(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = 100,
    offset: int = 0,
) -> dict:
    """List all transactions for a job (paginated)."""
    from sqlalchemy import func

    job = await db.get(AnalysisJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    _check_job_access(job, current_user)

    # Total count
    count_result = await db.execute(
        select(func.count()).select_from(Transaction).where(Transaction.job_id == job_id)
    )
    total = count_result.scalar() or 0

    # Paginated rows — nulls last for missing dates
    from sqlalchemy import nullslast
    result = await db.execute(
        select(Transaction)
        .where(Transaction.job_id == job_id)
        .order_by(nullslast(Transaction.transaction_date.desc()))
        .limit(limit)
        .offset(offset)
    )
    txs = result.scalars().all()

    return {
        "data": {
            "total": total,
            "limit": limit,
            "offset": offset,
            "transactions": [
                {
                    "id": tx.id,
                    "job_id": tx.job_id,
                    "amount_cents": tx.amount_kurus,
                    "currency": tx.currency,
                    "type": tx.type,
                    "category": tx.category,
                    "description": tx.description,
                    "vendor": tx.vendor,
                    "transaction_date": tx.transaction_date.isoformat() if tx.transaction_date else None,
                    "confidence": float(tx.confidence) if tx.confidence else None,
                    # Provenance. Each was persisted and none was returned, so
                    # the one screen a reviewer reads could not say why a row
                    # was held: that its date was invented, what the source
                    # document stated for tax, or what the parser noted.
                    "date_is_estimated": bool(tx.date_is_estimated),
                    "kdv_cents": tx.kdv_kurus,
                    "stopaj_cents": tx.stopaj_kurus,
                    "raw_text": tx.raw_text,
                }
                for tx in txs
            ],
        },
        "error": None,
    }
