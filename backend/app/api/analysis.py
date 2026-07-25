from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.transaction import Transaction

router = APIRouter()


class AnalyzeRequest(BaseModel):
    """Optional request body for POST /analyze/{job_id}."""
    budget_input: dict[str, Any] | None = None


@router.post("/analyze/{job_id}")
async def start_analysis(
    job_id: str,
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
    """
    from app.worker import enqueue_analysis

    job = await db.get(AnalysisJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job.status not in (JobStatus.PENDING, JobStatus.FAILED):
        raise HTTPException(
            status_code=409,
            detail=f"Job is already in status '{job.status}'. Cannot re-run.",
        )

    budget_input = body.budget_input if body else None
    await enqueue_analysis(job_id, budget_input)

    return {"data": {"job_id": job_id, "status": "queued"}, "error": None}


@router.get("/analysis/{job_id}")
async def get_analysis_status(
    job_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Poll job status and get logs."""
    job = await db.get(AnalysisJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
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
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Human approval — clear the awaiting_review flag to allow the pipeline to proceed."""
    job = await db.get(AnalysisJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    if not job.awaiting_review:
        raise HTTPException(status_code=409, detail="Job is not awaiting review.")
    job.awaiting_review = False
    job.status = JobStatus.PENDING
    job.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return {"data": {"job_id": job_id, "approved": True}, "error": None}


@router.get("/jobs")
async def list_jobs(
    db: AsyncSession = Depends(get_db),
    limit: int = 20,
) -> dict:
    """List the most recent analysis jobs (for sidebar history)."""
    result = await db.execute(
        select(AnalysisJob).order_by(desc(AnalysisJob.created_at)).limit(limit)
    )
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
    db: AsyncSession = Depends(get_db),
    limit: int = 100,
    offset: int = 0,
) -> dict:
    """List all transactions for a job (paginated)."""
    from sqlalchemy import func

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
                }
                for tx in txs
            ],
        },
        "error": None,
    }
