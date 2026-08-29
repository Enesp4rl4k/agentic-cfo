"""
CTO + CMO Kernel API Endpoints

POST /cto-kernel/analyze     -- CFO verilerinden CTO metrikleri uret
POST /cto-kernel/from-job    -- Job'dan CTO metrikleri uret
POST /cto-kernel/from-org    -- CompanyContext'ten CTO metrikleri uret

POST /cmo-kernel/analyze     -- CFO verilerinden CMO metrikleri uret
POST /cmo-kernel/from-job    -- Job'dan CMO metrikleri uret
POST /cmo-kernel/from-org    -- CompanyContext'ten CMO metrikleri uret
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.models.user import User

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Shared request schemas ─────────────────────────────────────────────────────

class KernelFromDataRequest(BaseModel):
    pnl:               dict[str, Any] | None = None
    cashflow:          dict[str, Any] | None = None
    forecast:          dict[str, Any] | None = None
    chro_data:         dict[str, Any] | None = None
    existing_cto_data: dict[str, Any] | None = None
    existing_cmo_data: dict[str, Any] | None = None
    company_size:      str = Field("smb", description="startup|smb|enterprise")
    industry:          str = Field("saas", description="saas|ecommerce|services")


class KernelFromJobRequest(BaseModel):
    job_id:       str
    company_size: str = "smb"
    industry:     str = "saas"


class KernelFromOrgRequest(BaseModel):
    org_id:       str
    company_size: str = "smb"
    industry:     str = "saas"


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
            "chro_data":         results.get("chro") or {},
            "existing_cto_data": results.get("cto") or {},
            "existing_cmo_data": results.get("cmo") or {},
        }
    except Exception as exc:
        logger.debug("Org context yuklenemedi: %s", exc)
        return {}


# ── CTO Kernel endpoints ──────────────────────────────────────────────────────

@router.post("/cto-kernel/analyze")
async def cto_kernel_analyze(
    req: KernelFromDataRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    CFO/CHRO verilerinden CTO metrikleri otomatik uret.
    Cloud billing CSV veya git log gerekmez.
    """
    from app.agents.cto.cto_kernel import run_cto_kernel
    try:
        return await run_cto_kernel(
            pnl=req.pnl, cashflow=req.cashflow, forecast=req.forecast,
            chro_data=req.chro_data, existing_cto_data=req.existing_cto_data,
            company_size=req.company_size,
        )
    except Exception as exc:
        logger.exception("CTO kernel hatasi: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/cto-kernel/from-job")
async def cto_kernel_from_job(
    req: KernelFromJobRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """CFO analiz job'undan CTO metrikleri uret."""
    from app.agents.cto.cto_kernel import run_cto_kernel
    from app.services.eng_signals import cto_existing_data_from_signals
    data = await _load_from_job(req.job_id, db)
    if not data:
        raise HTTPException(status_code=404, detail=f"Job {req.job_id} bulunamadi")
    # Real engineering signals (from a connector) win over CFO-financial extrapolation.
    org_id = str(current_user.org_id) if current_user.org_id else None
    existing = (
        await cto_existing_data_from_signals(org_id, db) if org_id else None
    )
    try:
        return await run_cto_kernel(
            pnl=data.get("pnl"), cashflow=data.get("cashflow"),
            forecast=data.get("forecast"), existing_cto_data=existing,
            company_size=req.company_size,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/cto-kernel/from-org")
async def cto_kernel_from_org(
    req: KernelFromOrgRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """CompanyContext'ten CTO metrikleri uret."""
    from app.agents.cto.cto_kernel import run_cto_kernel
    from app.services.eng_signals import cto_existing_data_from_signals
    ctx = await _load_from_org(req.org_id)
    if not ctx:
        raise HTTPException(status_code=404, detail=f"Org {req.org_id} verisi bulunamadi")
    existing = (
        await cto_existing_data_from_signals(req.org_id, db)
        or ctx.get("existing_cto_data")
    )
    try:
        return await run_cto_kernel(
            pnl=ctx.get("pnl"), cashflow=ctx.get("cashflow"),
            forecast=ctx.get("forecast"), chro_data=ctx.get("chro_data"),
            existing_cto_data=existing,
            company_size=req.company_size,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── CMO Kernel endpoints ──────────────────────────────────────────────────────

@router.post("/cmo-kernel/analyze")
async def cmo_kernel_analyze(
    req: KernelFromDataRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    CFO/CHRO verilerinden CMO metrikleri otomatik uret.
    Campaign CSV veya funnel verisi gerekmez.
    """
    from app.agents.cmo.cmo_kernel import run_cmo_kernel
    try:
        return await run_cmo_kernel(
            pnl=req.pnl, cashflow=req.cashflow, forecast=req.forecast,
            chro_data=req.chro_data, existing_cmo_data=req.existing_cmo_data,
            industry=req.industry,
        )
    except Exception as exc:
        logger.exception("CMO kernel hatasi: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/cmo-kernel/from-job")
async def cmo_kernel_from_job(
    req: KernelFromJobRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """CFO analiz job'undan CMO metrikleri uret."""
    from app.agents.cmo.cmo_kernel import run_cmo_kernel
    data = await _load_from_job(req.job_id, db)
    if not data:
        raise HTTPException(status_code=404, detail=f"Job {req.job_id} bulunamadi")
    try:
        return await run_cmo_kernel(
            pnl=data.get("pnl"), cashflow=data.get("cashflow"),
            forecast=data.get("forecast"), industry=req.industry,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/cmo-kernel/from-org")
async def cmo_kernel_from_org(
    req: KernelFromOrgRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """CompanyContext'ten CMO metrikleri uret."""
    from app.agents.cmo.cmo_kernel import run_cmo_kernel
    ctx = await _load_from_org(req.org_id)
    if not ctx:
        raise HTTPException(status_code=404, detail=f"Org {req.org_id} verisi bulunamadi")
    try:
        return await run_cmo_kernel(
            pnl=ctx.get("pnl"), cashflow=ctx.get("cashflow"),
            forecast=ctx.get("forecast"), chro_data=ctx.get("chro_data"),
            existing_cmo_data=ctx.get("existing_cmo_data"),
            industry=req.industry,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
