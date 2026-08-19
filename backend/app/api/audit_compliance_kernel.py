"""
Audit + Compliance Kernel API Endpoints

POST /audit-kernel/analyze       -- Mevcut verilerden denetim bulgulari uret
POST /audit-kernel/from-org      -- CompanyContext'ten denetim analizi
POST /compliance-kernel/analyze  -- Turkiye mevzuati uyum degerlendirmesi
POST /compliance-kernel/from-org -- CompanyContext'ten uyum analizi
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

class AuditKernelRequest(BaseModel):
    pnl:       dict[str, Any] | None = None
    cashflow:  dict[str, Any] | None = None
    anomalies: list[dict[str, Any]] = Field(default_factory=list)
    chro_data: dict[str, Any] | None = None
    cto_data:  dict[str, Any] | None = None
    coo_data:  dict[str, Any] | None = None


class ComplianceKernelRequest(BaseModel):
    pnl:           dict[str, Any] | None = None
    chro_data:     dict[str, Any] | None = None
    cto_data:      dict[str, Any] | None = None
    company_size:  str  = Field("smb",   description="startup|smb|enterprise")
    sector:        str  = Field("saas",  description="saas|ecommerce|fintech|services|retail")
    has_eu_customers: bool = False
    is_fintech:    bool = False
    monthly_invoice_count: int = 0


class KernelFromOrgRequest(BaseModel):
    org_id:       str
    company_size: str  = "smb"
    sector:       str  = "saas"
    has_eu_customers: bool = False
    is_fintech:   bool = False


# ── Context loader ─────────────────────────────────────────────────────────────

async def _load_from_org(org_id: str) -> dict[str, Any]:
    try:
        from app.services.company_context import get_company_context
        ctx = await get_company_context(org_id)
        if not ctx:
            return {}
        results = ctx.get("agent_results") or {}
        cfo_r   = results.get("cfo") or {}
        return {
            "pnl":       cfo_r.get("pnl") or {},
            "cashflow":  cfo_r.get("cashflow") or {},
            "anomalies": cfo_r.get("anomalies") or [],
            "chro_data": results.get("chro") or {},
            "cto_data":  results.get("cto") or {},
            "coo_data":  results.get("coo") or {},
        }
    except Exception as exc:
        logger.debug("Org context yuklenemedi: %s", exc)
        return {}


# ── Audit Kernel endpoints ─────────────────────────────────────────────────────

@router.post("/audit-kernel/analyze")
async def audit_kernel_analyze(
    req: AuditKernelRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Mevcut C-Suite verilerinden denetim bulgularini uret.
    CFO anomali tespiti, CTO guvenlik skoru ve CHRO turnover'dan
    otomatik audit bulgulari cikartir.
    """
    from app.agents.audit.audit_kernel import run_audit_kernel
    try:
        return await run_audit_kernel(
            pnl=req.pnl, cashflow=req.cashflow, anomalies=req.anomalies,
            chro_data=req.chro_data, cto_data=req.cto_data, coo_data=req.coo_data,
        )
    except Exception as exc:
        logger.exception("Audit kernel hatasi: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/audit-kernel/from-org")
async def audit_kernel_from_org(
    req: KernelFromOrgRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """CompanyContext'teki tum agent verilerinden denetim bulgulari uret."""
    from app.agents.audit.audit_kernel import run_audit_kernel
    ctx = await _load_from_org(req.org_id)
    if not ctx:
        raise HTTPException(status_code=404, detail=f"Org {req.org_id} verisi bulunamadi")
    try:
        return await run_audit_kernel(
            pnl=ctx.get("pnl"), cashflow=ctx.get("cashflow"),
            anomalies=ctx.get("anomalies", []),
            chro_data=ctx.get("chro_data"), cto_data=ctx.get("cto_data"),
            coo_data=ctx.get("coo_data"),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── Compliance Kernel endpoints ────────────────────────────────────────────────

@router.post("/compliance-kernel/analyze")
async def compliance_kernel_analyze(
    req: ComplianceKernelRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Turkiye mevzuati uyum degerlendirmesi.

    Kapsanan alanlar:
    - KVKK / VERBİS
    - e-Fatura / e-Arsiv (GIB)
    - SGK yukumlulukler
    - VUK / KDV beyanname
    - GDPR (AB musterisi varsa)
    - BDDK (fintech varsa)
    """
    from app.agents.compliance.compliance_kernel import run_compliance_kernel
    try:
        return await run_compliance_kernel(
            pnl=req.pnl, chro_data=req.chro_data, cto_data=req.cto_data,
            company_size=req.company_size, sector=req.sector,
            has_eu_customers=req.has_eu_customers, is_fintech=req.is_fintech,
            monthly_invoice_count=req.monthly_invoice_count,
        )
    except Exception as exc:
        logger.exception("Compliance kernel hatasi: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/compliance-kernel/from-org")
async def compliance_kernel_from_org(
    req: KernelFromOrgRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """CompanyContext'teki verilerden uyum degerlendirmesi yap."""
    from app.agents.compliance.compliance_kernel import run_compliance_kernel
    ctx = await _load_from_org(req.org_id)
    try:
        return await run_compliance_kernel(
            pnl=ctx.get("pnl"), chro_data=ctx.get("chro_data"),
            cto_data=ctx.get("cto_data"),
            company_size=req.company_size, sector=req.sector,
            has_eu_customers=req.has_eu_customers, is_fintech=req.is_fintech,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
