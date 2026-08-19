"""
Multi-Period Comparison API — DQ-4

POST /comparison/multi-period
    Compare 2-3 analysis jobs side by side.
    Returns revenue, margin, cash flow, OpEx trends + change indicators.

GET  /comparison/jobs
    List the user's completed analysis jobs (for selecting periods).
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.models.analysis_job import AnalysisJob
from app.models.user import User
from app.services.multi_period_comparison import (
    MultiPeriodComparisonEngine,
    _extract_period_data,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["comparison"])


class MultiPeriodRequest(BaseModel):
    job_ids: list[str]

    @field_validator("job_ids")
    @classmethod
    def validate_job_count(cls, v: list[str]) -> list[str]:
        if len(v) < 2:
            raise ValueError("En az 2 job_id gereklidir.")
        if len(v) > 3:
            raise ValueError("En fazla 3 dönem karşılaştırılabilir.")
        return v


@router.post("/comparison/multi-period")
async def multi_period_comparison(
    body: MultiPeriodRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Compare 2-3 completed analysis jobs.
    Returns period metrics, change indicators, trend series and narrative.
    """
    org_id = str(user.org_id) if user.org_id else str(user.id)

    # Load jobs
    result = await db.execute(
        select(AnalysisJob).where(AnalysisJob.id.in_(body.job_ids))
    )
    jobs = result.scalars().all()

    if len(jobs) < 2:
        raise HTTPException(
            status_code=404,
            detail=f"Yalnızca {len(jobs)} job bulundu, {len(body.job_ids)} istendi."
        )

    # Extract period data from each job
    period_data_list = []
    for job in jobs:
        try:
            result_meta = job.result_metadata or {}
            period = _extract_period_data(str(job.id), result_meta)
            period_data_list.append(period)
        except Exception as e:
            logger.warning("Failed to extract period data from job %s: %s", job.id, e)

    if len(period_data_list) < 2:
        raise HTTPException(
            status_code=422,
            detail="Analiz sonuçları çıkarılamadı. Job'ların tamamlanmış olduğundan emin olun."
        )

    # Run comparison
    try:
        engine = MultiPeriodComparisonEngine()
        report = engine.compare(period_data_list)
    except Exception as e:
        logger.error("Comparison engine error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

    return {"data": report.to_dict(), "error": None}


@router.get("/comparison/jobs")
async def list_completed_jobs(
    limit: int = 20,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    List completed analysis jobs for the current user/org.
    Used by the comparison UI to let users pick periods.
    """
    org_id = str(user.org_id) if user.org_id else None

    query = (
        select(AnalysisJob)
        .where(AnalysisJob.status == "completed")
        .order_by(AnalysisJob.created_at.desc())
        .limit(limit)
    )

    if org_id:
        query = query.where(AnalysisJob.org_id == org_id)
    else:
        query = query.where(AnalysisJob.user_id == str(user.id))

    result = await db.execute(query)
    jobs = result.scalars().all()

    job_list = []
    for job in jobs:
        meta = job.result_metadata or {}
        pnl = meta.get("pnl") or {}
        job_list.append({
            "job_id": str(job.id),
            "filename": job.filename,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "status": job.status,
            "period_label": meta.get("period_label") or pnl.get("period") or str(job.id)[:8],
            "revenue": pnl.get("revenue"),
            "date_from": meta.get("date_from") or pnl.get("period_start"),
            "date_to": meta.get("date_to") or pnl.get("period_end"),
        })

    return {"data": {"jobs": job_list, "total": len(job_list)}, "error": None}
