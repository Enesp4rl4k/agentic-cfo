"""
Risk + zincirleme etki API — ölçülmüş risk göstergelerinden.

POST /risk-cascade/analyze   -- verilen CFO verisi ve risk sonucundan
POST /risk-cascade/from-job  -- işin CFO raporu + kurumun son risk sonucu
POST /risk-cascade/from-org  -- kurumun son CFO ve risk sonuçları

The job loader read `Report.format` and `row.content`, attributes the model
does not have, so /from-job always answered 404; the org loader read a context
field that does not exist. Both fed the risk kernel's invented KRIs. See
app/agents/risk/gercek_kri.py.
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


class RiskCascadeRequest(BaseModel):
    pnl:          dict[str, Any] | None = None
    cashflow:     dict[str, Any] | None = None
    forecast:     dict[str, Any] | None = None
    risk_result:  dict[str, Any] | None = None
    max_cascades: int = Field(5, ge=1, le=10)
    only_red:     bool = False


class RiskCascadeFromJobRequest(BaseModel):
    job_id:       str
    max_cascades: int = Field(5, ge=1, le=10)
    only_red:     bool = False


class RiskCascadeFromOrgRequest(BaseModel):
    org_id:       str
    max_cascades: int = Field(5, ge=1, le=10)
    only_red:     bool = False


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


async def _org_context(org_id: str, db: AsyncSession) -> tuple[dict[str, Any], dict[str, Any] | None]:
    from app.services.company_context import get_company_context

    ctx = await get_company_context(org_id, db)
    return (getattr(ctx, "last_cfo_result", None) or {}), getattr(ctx, "last_risk_result", None)


@router.post("/risk-cascade/analyze")
async def risk_cascade_analyze(
    req: RiskCascadeRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    from app.agents.orchestration.risk_cascade_bridge import run_risk_cascade_analysis

    return await run_risk_cascade_analysis(
        pnl=req.pnl, cashflow=req.cashflow, forecast=req.forecast, risk_result=req.risk_result,
        max_cascades=req.max_cascades, only_red=req.only_red,
    )


@router.post("/risk-cascade/from-job")
async def risk_cascade_from_job(
    req: RiskCascadeFromJobRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from app.agents.orchestration.risk_cascade_bridge import run_risk_cascade_analysis

    job = await load_owned_job(db, req.job_id, current_user)
    data = await _cfo_report(job.id, db)
    if not data:
        raise HTTPException(status_code=404, detail=f"Job {req.job_id} için CFO raporu yok")
    risk_result = (await _org_context(str(job.org_id), db))[1] if job.org_id else None
    return await run_risk_cascade_analysis(
        pnl=data.get("pnl"), cashflow=data.get("cashflow"), forecast=data.get("forecast"),
        risk_result=risk_result, max_cascades=req.max_cascades, only_red=req.only_red,
    )


@router.post("/risk-cascade/from-org")
async def risk_cascade_from_org(
    req: RiskCascadeFromOrgRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from app.agents.orchestration.risk_cascade_bridge import run_risk_cascade_analysis

    if not current_user_org_matches(current_user, req.org_id):
        raise HTTPException(status_code=404, detail="Kayıt bulunamadı.")
    cfo, risk_result = await _org_context(req.org_id, db)
    return await run_risk_cascade_analysis(
        pnl=cfo.get("pnl"), cashflow=cfo.get("cashflow"), forecast=cfo.get("forecast"),
        risk_result=risk_result, max_cascades=req.max_cascades, only_red=req.only_red,
    )
