"""
Cross-Domain Intelligence Hub API

POST /cross-domain/analyze    -- Tum kernel'lari calistir, cross-domain raporu uret
POST /cross-domain/from-job   -- CFO job'undan tam analiz
POST /cross-domain/from-org   -- CompanyContext'ten tam analiz
GET  /cross-domain/health     -- Sadece saglik skoru (hafif endpoint)
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

class CrossDomainRequest(BaseModel):
    pnl:           dict[str, Any] | None = None
    cashflow:      dict[str, Any] | None = None
    forecast:      dict[str, Any] | None = None
    anomalies:     list[dict[str, Any]] = Field(default_factory=list)
    existing_cto:  dict[str, Any] | None = None
    existing_cmo:  dict[str, Any] | None = None
    existing_chro: dict[str, Any] | None = None
    existing_coo:  dict[str, Any] | None = None
    company_size:  str  = Field("smb",  description="startup|smb|enterprise")
    sector:        str  = Field("saas", description="saas|ecommerce|fintech|services|retail")
    has_eu_customers: bool = False
    is_fintech:    bool = False


class CrossDomainFromJobRequest(BaseModel):
    job_id:        str
    company_size:  str  = "smb"
    sector:        str  = "saas"
    has_eu_customers: bool = False
    is_fintech:    bool = False


class CrossDomainFromOrgRequest(BaseModel):
    org_id:        str
    company_size:  str  = "smb"
    sector:        str  = "saas"
    has_eu_customers: bool = False
    is_fintech:    bool = False


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
        cfo_r   = results.get("cfo") or {}
        return {
            "pnl":      cfo_r.get("pnl") or {},
            "cashflow": cfo_r.get("cashflow") or {},
            "forecast": cfo_r.get("forecast") or {},
            "anomalies": cfo_r.get("anomalies") or [],
            "existing_cto":  results.get("cto") or {},
            "existing_cmo":  results.get("cmo") or {},
            "existing_chro": results.get("chro") or {},
            "existing_coo":  results.get("coo") or {},
        }
    except Exception as exc:
        logger.debug("Org context yuklenemedi: %s", exc)
        return {}


# ── Endpoint'ler ───────────────────────────────────────────────────────────────

@router.post("/cross-domain/analyze")
async def cross_domain_analyze(
    req: CrossDomainRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Tum C-Suite kernel'larini paralel calistir ve cross-domain rapor uret.

    Tek API cagriyla:
    - CTO, CMO, CHRO, COO, Audit, Compliance, Risk kernel'lari calisir
    - Cross-domain iliski tespiti yapilir (Talent-Cash Cascade, Delivery Risk, vb.)
    - Genel sirket saglik skoru hesaplanir (0-100)
    - Oncelikli aksiyonlar ve hizli kazanimlar listelenir
    """
    from app.services.cross_domain_hub import run_cross_domain_analysis
    try:
        return await run_cross_domain_analysis(
            pnl=req.pnl, cashflow=req.cashflow, forecast=req.forecast,
            anomalies=req.anomalies,
            existing_cto=req.existing_cto, existing_cmo=req.existing_cmo,
            existing_chro=req.existing_chro, existing_coo=req.existing_coo,
            company_size=req.company_size, sector=req.sector,
            has_eu_customers=req.has_eu_customers, is_fintech=req.is_fintech,
        )
    except Exception as exc:
        logger.exception("Cross-domain analiz hatasi: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/cross-domain/from-job")
async def cross_domain_from_job(
    req: CrossDomainFromJobRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """CFO analiz job'undan tam cross-domain analiz."""
    from app.services.cross_domain_hub import run_cross_domain_analysis
    data = await _load_from_job(req.job_id, db)
    if not data:
        raise HTTPException(status_code=404, detail=f"Job {req.job_id} bulunamadi")
    try:
        return await run_cross_domain_analysis(
            pnl=data.get("pnl"), cashflow=data.get("cashflow"),
            forecast=data.get("forecast"),
            company_size=req.company_size, sector=req.sector,
            has_eu_customers=req.has_eu_customers, is_fintech=req.is_fintech,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/cross-domain/from-org")
async def cross_domain_from_org(
    req: CrossDomainFromOrgRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """CompanyContext'teki tum agent verilerinden cross-domain analiz."""
    from app.services.cross_domain_hub import run_cross_domain_analysis
    ctx = await _load_from_org(req.org_id)
    if not ctx:
        raise HTTPException(status_code=404, detail=f"Org {req.org_id} verisi bulunamadi")
    try:
        return await run_cross_domain_analysis(
            pnl=ctx.get("pnl"), cashflow=ctx.get("cashflow"),
            forecast=ctx.get("forecast"), anomalies=ctx.get("anomalies", []),
            existing_cto=ctx.get("existing_cto"), existing_cmo=ctx.get("existing_cmo"),
            existing_chro=ctx.get("existing_chro"), existing_coo=ctx.get("existing_coo"),
            company_size=req.company_size, sector=req.sector,
            has_eu_customers=req.has_eu_customers, is_fintech=req.is_fintech,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/cross-domain/health/{org_id}")
async def cross_domain_health(
    org_id: str,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Hafif saglik skoru endpoint'i.
    Tam analiz yerine sadece genel saglik durumunu doner (dashboard header icin).
    """
    from app.services.cross_domain_hub import run_cross_domain_analysis
    ctx = await _load_from_org(org_id)
    if not ctx:
        return {"health_score": None, "health_label": "no_data", "error": "Veri bulunamadi"}
    try:
        result = await run_cross_domain_analysis(
            pnl=ctx.get("pnl"), cashflow=ctx.get("cashflow"),
            forecast=ctx.get("forecast"),
            existing_cto=ctx.get("existing_cto"), existing_cmo=ctx.get("existing_cmo"),
            existing_chro=ctx.get("existing_chro"), existing_coo=ctx.get("existing_coo"),
        )
        return {
            "health_score":    result.get("overall_health_score"),
            "health_label":    result.get("health_label"),
            "critical_count":  result.get("critical_count", 0),
            "high_count":      result.get("high_count", 0),
            "executive_summary": result.get("executive_summary", ""),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
