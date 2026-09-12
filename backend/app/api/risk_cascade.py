"""
Risk Cascade Bridge API

POST /risk-cascade/analyze     -- KRI uret + cascade simulasyonu birlestir
POST /risk-cascade/from-job    -- CFO job'undan tam analiz
POST /risk-cascade/from-org    -- CompanyContext'ten tam analiz
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


# ── Request schemalar ─────────────────────────────────────────────────────────

class RiskCascadeRequest(BaseModel):
    pnl:          dict[str, Any] | None = None
    cashflow:     dict[str, Any] | None = None
    forecast:     dict[str, Any] | None = None
    chro_data:    dict[str, Any] | None = None
    cto_data:     dict[str, Any] | None = None
    cmo_data:     dict[str, Any] | None = None
    coo_data:     dict[str, Any] | None = None
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


# ── Context loaders ───────────────────────────────────────────────────────────

async def _load_from_job(job_id: str, db: AsyncSession) -> dict[str, Any]:
    try:
        from app.models.report import Report, ReportFormat  # type: ignore[attr-defined]
        stmt = (
            select(Report)
            .where(Report.job_id == job_id, Report.format == ReportFormat.JSON)
            .order_by(desc(Report.created_at))
            .limit(1)
        )
        row = (await db.execute(stmt)).scalar_one_or_none()
        if not row or not row.content:
            return {}
        import json
        data = json.loads(row.content) if isinstance(row.content, str) else row.content
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.debug("Job yuklenemedi: %s", exc)
        return {}


async def _load_from_org(org_id: str) -> dict[str, Any]:
    try:
        from app.services.company_context import get_company_context
        ctx = await get_company_context(org_id)
        if not ctx:
            return {}
        results = ctx.get("agent_results") or {}
        cfo_r = results.get("cfo") or {}
        return {
            "pnl":      cfo_r.get("pnl") or {},
            "cashflow": cfo_r.get("cashflow") or {},
            "forecast": cfo_r.get("forecast") or {},
            "chro_data": results.get("chro") or {},
            "cto_data":  results.get("cto") or {},
            "cmo_data":  results.get("cmo") or {},
            "coo_data":  results.get("coo") or {},
        }
    except Exception as exc:
        logger.debug("Org context yuklenemedi: %s", exc)
        return {}


# ── Endpoint'ler ───────────────────────────────────────────────────────────────

@router.post("/risk-cascade/analyze")
async def risk_cascade_analyze(
    req: RiskCascadeRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    KRI uretimi + cascade simulasyonunu tek cagriyla calistir.

    1. C-Suite verilerinden KRI'lari uretir
    2. Red/amber KRI'larda cascade_trigger varsa simulasyonu calistirir
    3. KRI + cascade etkisi tek raporda doner

    max_cascades: performans icin max simulasyon sayisi (varsayilan 5)
    only_red: sadece RED KRI'lari cascade'e sok
    """
    from app.agents.orchestration.risk_cascade_bridge import run_risk_cascade_analysis
    try:
        return await run_risk_cascade_analysis(
            pnl=req.pnl,
            cashflow=req.cashflow,
            forecast=req.forecast,
            chro_data=req.chro_data,
            cto_data=req.cto_data,
            cmo_data=req.cmo_data,
            coo_data=req.coo_data,
            max_cascades=req.max_cascades,
            only_red=req.only_red,
        )
    except Exception as exc:
        logger.exception("Risk cascade analiz hatasi: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/risk-cascade/from-job")
async def risk_cascade_from_job(
    req: RiskCascadeFromJobRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """CFO analiz job'undan tam risk + cascade analizi."""
    from app.agents.orchestration.risk_cascade_bridge import run_risk_cascade_analysis
    # A job id from the request body, loaded without asking whose it was.
    if req.job_id:
        await load_owned_job(db, req.job_id, current_user)
    data = await _load_from_job(req.job_id, db)
    if not data:
        raise HTTPException(status_code=404, detail=f"Job {req.job_id} bulunamadi")
    try:
        return await run_risk_cascade_analysis(
            pnl=data.get("pnl"),
            cashflow=data.get("cashflow"),
            forecast=data.get("forecast"),
            max_cascades=req.max_cascades,
            only_red=req.only_red,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/risk-cascade/from-org")
async def risk_cascade_from_org(
    req: RiskCascadeFromOrgRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """CompanyContext'teki tum agent verilerinden risk + cascade analizi."""
    from app.agents.orchestration.risk_cascade_bridge import run_risk_cascade_analysis
    # The organisation came from the request, never compared with the caller's.
    if not current_user_org_matches(current_user, req.org_id):
        raise HTTPException(status_code=404, detail="Kayıt bulunamadı.")
    ctx = await _load_from_org(req.org_id)
    if not ctx:
        raise HTTPException(status_code=404, detail=f"Org {req.org_id} verisi bulunamadi")
    try:
        return await run_risk_cascade_analysis(
            **ctx,
            max_cascades=req.max_cascades,
            only_red=req.only_red,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
