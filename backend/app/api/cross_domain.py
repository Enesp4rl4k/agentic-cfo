"""
Çapraz alan analizi API — yalnızca gerçek alan sonuçlarıyla.

POST /cross-domain/analyze    -- verilen alan sonuçlarından rapor
POST /cross-domain/from-job   -- işin CFO raporu + kurumun son alan sonuçları
POST /cross-domain/from-org   -- kurumun son alan sonuçları
GET  /cross-domain/health/{org_id} -- yalnızca sağlık skoru

These ran the seven kernels, and the organisation routes read a context field
that does not exist, so they only ever saw estimates. See
app/agents/orchestration/cross_domain_hub.py.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.access import current_user_org_matches, load_owned_job
from app.api.auth import get_current_user
from app.database import get_db
from app.models.user import User

router = APIRouter()
logger = logging.getLogger(__name__)


class CrossDomainRequest(BaseModel):
    domain_results: dict[str, dict[str, Any] | None] = Field(default_factory=dict)
    pnl:            dict[str, Any] | None = None
    forecast:       dict[str, Any] | None = None


class CrossDomainFromJobRequest(BaseModel):
    job_id: str


class CrossDomainFromOrgRequest(BaseModel):
    org_id: str


async def _cfo_report(job_id: str, db: AsyncSession) -> dict[str, Any]:
    from app.models.report import Report, ReportFormat

    row = (
        await db.execute(
            select(Report)
            .where(Report.job_id == job_id, Report.report_format == ReportFormat.JSON)
            .order_by(desc(Report.created_at))
            .limit(1)
        )
    ).scalar_one_or_none()
    return row.data if row and isinstance(row.data, dict) else {}


@router.post("/cross-domain/analyze")
async def cross_domain_analyze(
    req: CrossDomainRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    from app.agents.orchestration.cross_domain_hub import run_cross_domain_analysis

    return await run_cross_domain_analysis(
        domain_results=req.domain_results, pnl=req.pnl, forecast=req.forecast,
    )


@router.post("/cross-domain/from-job")
async def cross_domain_from_job(
    req: CrossDomainFromJobRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from app.agents.orchestration.cross_domain_hub import load_org_inputs, run_cross_domain_analysis

    job = await load_owned_job(db, req.job_id, current_user)
    data = await _cfo_report(job.id, db)
    if not data:
        raise HTTPException(status_code=404, detail=f"Job {req.job_id} için CFO raporu yok")
    domains: dict[str, Any] = {}
    if job.org_id:
        domains = (await load_org_inputs(str(job.org_id), db))["domain_results"]
    return await run_cross_domain_analysis(
        domain_results=domains, pnl=data.get("pnl"), forecast=data.get("forecast"),
    )


@router.post("/cross-domain/from-org")
async def cross_domain_from_org(
    req: CrossDomainFromOrgRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from app.agents.orchestration.cross_domain_hub import load_org_inputs, run_cross_domain_analysis

    if not current_user_org_matches(current_user, req.org_id):
        raise HTTPException(status_code=404, detail="Kayıt bulunamadı.")
    return await run_cross_domain_analysis(**(await load_org_inputs(req.org_id, db)))


@router.get("/cross-domain/health/{org_id}")
async def cross_domain_health(
    org_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from app.agents.orchestration.cross_domain_hub import load_org_inputs, run_cross_domain_analysis

    if not current_user_org_matches(current_user, org_id):
        raise HTTPException(status_code=404, detail="Kayıt bulunamadı.")
    result = await run_cross_domain_analysis(**(await load_org_inputs(org_id, db)))
    return {
        "health_score": result["overall_health_score"],
        "health_label": result["health_label"] or "no_data",
        "health_components": result["health_components"],
        "analyzed_domains": result["analyzed_domains"],
        "critical_count": result["critical_count"],
        "high_count": result["high_count"],
        "executive_summary": result["executive_summary"],
    }
