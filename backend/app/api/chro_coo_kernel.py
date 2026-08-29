"""
CHRO + COO Kernel API Endpoints

POST /chro-kernel/analyze     -- CFO verilerinden CHRO metrikleri uret
POST /chro-kernel/from-job    -- Job'dan CHRO metrikleri uret
POST /chro-kernel/from-org    -- CompanyContext'ten CHRO metrikleri uret

POST /coo-kernel/analyze      -- C-Suite verilerinden COO metrikleri uret
POST /coo-kernel/from-job     -- Job'dan COO metrikleri uret
POST /coo-kernel/from-org     -- CompanyContext'ten COO metrikleri uret
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


# ── Request schemalar ─────────────────────────────────────────────────────────

class CHROKernelRequest(BaseModel):
    pnl:                dict[str, Any] | None = None
    cashflow:           dict[str, Any] | None = None
    forecast:           dict[str, Any] | None = None
    existing_chro_data: dict[str, Any] | None = None
    company_size:       str = Field("smb", description="startup|smb|enterprise")


class COOKernelRequest(BaseModel):
    pnl:               dict[str, Any] | None = None
    cashflow:          dict[str, Any] | None = None
    chro_data:         dict[str, Any] | None = None
    cto_data:          dict[str, Any] | None = None
    cmo_data:          dict[str, Any] | None = None
    existing_coo_data: dict[str, Any] | None = None
    company_size:      str = Field("smb", description="startup|smb|enterprise")


class KernelFromJobRequest(BaseModel):
    job_id:       str
    company_size: str = "smb"


class KernelFromOrgRequest(BaseModel):
    org_id:       str
    company_size: str = "smb"


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
            "chro_data":          results.get("chro") or {},
            "cto_data":           results.get("cto") or {},
            "cmo_data":           results.get("cmo") or {},
            "existing_chro_data": results.get("chro") or {},
            "existing_coo_data":  results.get("coo") or {},
        }
    except Exception as exc:
        logger.debug("Org context yuklenemedi: %s", exc)
        return {}


# ── CHRO Kernel endpoints ─────────────────────────────────────────────────────

@router.post("/chro-kernel/analyze")
async def chro_kernel_analyze(
    req: CHROKernelRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    CFO verilerinden CHRO metrikleri otomatik uret.
    Headcount CSV, attrition CSV gerektirmez.
    """
    from app.agents.chro.chro_kernel import run_chro_kernel
    try:
        return await run_chro_kernel(
            pnl=req.pnl, cashflow=req.cashflow, forecast=req.forecast,
            existing_chro_data=req.existing_chro_data, company_size=req.company_size,
        )
    except Exception as exc:
        logger.exception("CHRO kernel hatasi: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/chro-kernel/from-job")
async def chro_kernel_from_job(
    req: KernelFromJobRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """CFO analiz job'undan CHRO metrikleri uret."""
    from app.agents.chro.chro_kernel import run_chro_kernel
    data = await _load_from_job(req.job_id, db)
    if not data:
        raise HTTPException(status_code=404, detail=f"Job {req.job_id} bulunamadi")
    try:
        return await run_chro_kernel(
            pnl=data.get("pnl"), cashflow=data.get("cashflow"),
            forecast=data.get("forecast"), company_size=req.company_size,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/chro-kernel/from-org")
async def chro_kernel_from_org(
    req: KernelFromOrgRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """CompanyContext'ten CHRO metrikleri uret."""
    from app.agents.chro.chro_kernel import run_chro_kernel
    ctx = await _load_from_org(req.org_id)
    if not ctx:
        raise HTTPException(status_code=404, detail=f"Org {req.org_id} verisi bulunamadi")
    try:
        return await run_chro_kernel(
            pnl=ctx.get("pnl"), cashflow=ctx.get("cashflow"),
            forecast=ctx.get("forecast"),
            existing_chro_data=ctx.get("existing_chro_data"),
            company_size=req.company_size,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── COO Kernel endpoints ──────────────────────────────────────────────────────

@router.post("/coo-kernel/analyze")
async def coo_kernel_analyze(
    req: COOKernelRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    C-Suite verilerinden COO metrikleri otomatik uret.
    SLA CSV, process CSV gerektirmez.
    """
    from app.agents.coo.coo_kernel import run_coo_kernel
    try:
        return await run_coo_kernel(
            pnl=req.pnl, cashflow=req.cashflow,
            chro_data=req.chro_data, cto_data=req.cto_data, cmo_data=req.cmo_data,
            existing_coo_data=req.existing_coo_data, company_size=req.company_size,
        )
    except Exception as exc:
        logger.exception("COO kernel hatasi: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/coo-kernel/from-job")
async def coo_kernel_from_job(
    req: KernelFromJobRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """CFO analiz job'undan COO metrikleri uret."""
    from app.agents.coo.coo_kernel import run_coo_kernel
    data = await _load_from_job(req.job_id, db)
    if not data:
        raise HTTPException(status_code=404, detail=f"Job {req.job_id} bulunamadi")
    try:
        return await run_coo_kernel(
            pnl=data.get("pnl"), cashflow=data.get("cashflow"),
            company_size=req.company_size,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/coo-kernel/from-org")
async def coo_kernel_from_org(
    req: KernelFromOrgRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """CompanyContext'teki tum verilerden COO metrikleri uret."""
    from app.agents.coo.coo_kernel import run_coo_kernel
    ctx = await _load_from_org(req.org_id)
    if not ctx:
        raise HTTPException(status_code=404, detail=f"Org {req.org_id} verisi bulunamadi")
    try:
        return await run_coo_kernel(
            pnl=ctx.get("pnl"), cashflow=ctx.get("cashflow"),
            chro_data=ctx.get("chro_data"), cto_data=ctx.get("cto_data"),
            cmo_data=ctx.get("cmo_data"),
            existing_coo_data=ctx.get("existing_coo_data"),
            company_size=req.company_size,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
