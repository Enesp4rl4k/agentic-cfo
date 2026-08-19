"""
Risk Kernel API

POST /risk-kernel/analyze        -- C-Suite verilerinden KRI uret
POST /risk-kernel/from-job       -- CFO job'undan KRI uret
POST /risk-kernel/from-org       -- CompanyContext'ten KRI uret
GET  /risk-kernel/kri-categories -- KRI kategorileri
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from app.api.auth import get_current_user
from app.database import get_db
from app.models.user import User

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Request schemalar ─────────────────────────────────────────────────────────

class RiskKernelRequest(BaseModel):
    pnl:       dict[str, Any] | None = None
    cashflow:  dict[str, Any] | None = None
    forecast:  dict[str, Any] | None = None
    chro_data: dict[str, Any] | None = None
    cto_data:  dict[str, Any] | None = None
    cmo_data:  dict[str, Any] | None = None
    coo_data:  dict[str, Any] | None = None


class RiskKernelFromJobRequest(BaseModel):
    job_id: str
    include_cascade_triggers: bool = True


class RiskKernelFromOrgRequest(BaseModel):
    org_id: str
    include_cascade_triggers: bool = True


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

@router.post("/risk-kernel/analyze")
async def risk_kernel_analyze(
    req: RiskKernelRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    C-Suite verilerinden otomatik KRI uret ve risk pozisyonunu hesapla.

    CSV gerektirmez -- dogrudan CFO/CHRO/CTO/CMO/COO verisi ile calisir.
    KRI'lar red/amber/green statusu ve trajectory tahminiyle doner.
    """
    from app.agents.risk.risk_kernel import run_risk_kernel
    try:
        return await run_risk_kernel(
            pnl=req.pnl,
            cashflow=req.cashflow,
            forecast=req.forecast,
            chro_data=req.chro_data,
            cto_data=req.cto_data,
            cmo_data=req.cmo_data,
            coo_data=req.coo_data,
        )
    except Exception as exc:
        logger.exception("Risk kernel hatasi: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/risk-kernel/from-job")
async def risk_kernel_from_job(
    req: RiskKernelFromJobRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """CFO analiz job'undan KRI uret."""
    from app.agents.risk.risk_kernel import run_risk_kernel
    data = await _load_from_job(req.job_id, db)
    if not data:
        raise HTTPException(status_code=404, detail=f"Job {req.job_id} bulunamadi")
    try:
        return await run_risk_kernel(
            pnl=data.get("pnl"),
            cashflow=data.get("cashflow"),
            forecast=data.get("forecast"),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/risk-kernel/from-org")
async def risk_kernel_from_org(
    req: RiskKernelFromOrgRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """CompanyContext'teki tum agent sonuclarindan KRI uret."""
    from app.agents.risk.risk_kernel import run_risk_kernel
    ctx = await _load_from_org(req.org_id)
    if not ctx:
        raise HTTPException(status_code=404, detail=f"Org {req.org_id} verisi bulunamadi")
    try:
        return await run_risk_kernel(**ctx)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/risk-kernel/kri-categories")
async def kri_categories(
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """KRI kategorileri ve aciklamalari."""
    return {
        "categories": [
            {"id": "financial",   "label": "Finansal",           "icon": "TrendingDown", "color": "blue"},
            {"id": "people",      "label": "Insan Kaynaklari",   "icon": "Users",        "color": "purple"},
            {"id": "technology",  "label": "Teknoloji",          "icon": "Cpu",          "color": "cyan"},
            {"id": "market",      "label": "Pazar",              "icon": "BarChart2",    "color": "green"},
            {"id": "operational", "label": "Operasyon",          "icon": "Settings",     "color": "orange"},
            {"id": "compliance",  "label": "Uyumluluk",          "icon": "Shield",       "color": "red"},
        ]
    }
