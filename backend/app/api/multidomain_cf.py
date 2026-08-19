"""
Multi-Domain Counterfactual API

POST /multidomain-cf/headcount    -- Personel degisimi (CFO+CHRO+CTO+CMO)
POST /multidomain-cf/marketing    -- Pazarlama yatirimi
POST /multidomain-cf/tech         -- Teknoloji yatirimi
GET  /multidomain-cf/actions      -- Desteklenen aksiyon listesi
"""
from __future__ import annotations

import logging
from typing import Any, Literal

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

class HeadcountMDRequest(BaseModel):
    delta: int = Field(..., description="Pozitif = ise al, negatif = cikar")
    avg_monthly_salary_try: float | None = Field(None, gt=0)
    productivity_gain_pct: float = Field(0.10, ge=0, le=1.0)
    onboarding_months: int = Field(2, ge=0, le=6)
    horizon_months: int = Field(12, ge=1, le=36)
    role_type: Literal["engineer", "sales", "ops", "general"] = "general"
    job_id: str | None = None
    org_id: str | None = None


class MarketingMDRequest(BaseModel):
    monthly_increase_try: float = Field(..., gt=0)
    expected_roas: float = Field(2.5, gt=0, le=20)
    horizon_months: int = Field(12, ge=1, le=36)
    job_id: str | None = None
    org_id: str | None = None


class TechInvestMDRequest(BaseModel):
    one_time_invest_try: float = Field(..., gt=0)
    monthly_ops_increase_try: float = Field(0.0, ge=0)
    velocity_gain_pct: float = Field(0.15, gt=0, le=1.0)
    horizon_months: int = Field(12, ge=1, le=36)
    job_id: str | None = None
    org_id: str | None = None


# ── Context loader ─────────────────────────────────────────────────────────────

async def _load_ctx(
    job_id: str | None,
    org_id: str | None,
    db: AsyncSession,
) -> dict[str, Any]:
    if job_id:
        from app.models.report import Report, ReportFormat  # type: ignore[attr-defined]
        stmt = (
            select(Report)
            .where(Report.job_id == job_id, Report.format == ReportFormat.JSON)
            .order_by(desc(Report.created_at))
            .limit(1)
        )
        row = (await db.execute(stmt)).scalar_one_or_none()
        if row and row.content:
            try:
                import json
                data = json.loads(row.content) if isinstance(row.content, str) else row.content
                return {
                    "pnl":      data.get("pnl") or {},
                    "cashflow": data.get("cashflow") or {},
                    "forecast": data.get("forecast") or {},
                }
            except Exception:
                pass

    if org_id:
        try:
            from app.services.company_context import get_company_context
            ctx = await get_company_context(org_id)
            if ctx:
                results = ctx.get("agent_results") or {}
                cfo_r = results.get("cfo") or {}
                return {
                    "pnl":       cfo_r.get("pnl") or {},
                    "cashflow":  cfo_r.get("cashflow") or {},
                    "forecast":  cfo_r.get("forecast") or {},
                    "chro_data": results.get("chro") or {},
                    "cto_data":  results.get("cto") or {},
                    "cmo_data":  results.get("cmo") or {},
                    "coo_data":  results.get("coo") or {},
                }
        except Exception as exc:
            logger.debug("Context yuklenemedi: %s", exc)

    return {}


# ── Endpoint'ler ───────────────────────────────────────────────────────────────

@router.post("/multidomain-cf/headcount")
async def multidomain_headcount(
    req: HeadcountMDRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Personel degisiminin CFO + CHRO + CTO + CMO uzerindeki
    birlesik etkisini 3 senaryoyla gosterir.
    """
    from app.services.multidomain_counterfactual import get_multidomain_cf

    ctx = await _load_ctx(req.job_id, req.org_id, db)
    engine = get_multidomain_cf(**ctx)

    try:
        result = engine.analyze_headcount_change(
            delta=req.delta,
            avg_monthly_salary_try=req.avg_monthly_salary_try,
            productivity_gain_pct=req.productivity_gain_pct,
            onboarding_months=req.onboarding_months,
            horizon_months=req.horizon_months,
            role_type=req.role_type,
        )
    except Exception as exc:
        logger.exception("Headcount MD CF hatasi: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    return result.to_dict()


@router.post("/multidomain-cf/marketing")
async def multidomain_marketing(
    req: MarketingMDRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Pazarlama yatiriminin CFO + CMO + COO uzerindeki birlesik etkisi."""
    from app.services.multidomain_counterfactual import get_multidomain_cf

    ctx = await _load_ctx(req.job_id, req.org_id, db)
    engine = get_multidomain_cf(**ctx)

    try:
        result = engine.analyze_marketing_investment(
            monthly_increase_try=req.monthly_increase_try,
            expected_roas=req.expected_roas,
            horizon_months=req.horizon_months,
        )
    except Exception as exc:
        logger.exception("Marketing MD CF hatasi: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    return result.to_dict()


@router.post("/multidomain-cf/tech")
async def multidomain_tech(
    req: TechInvestMDRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Teknoloji yatiriminin CFO + CTO + COO uzerindeki birlesik etkisi."""
    from app.services.multidomain_counterfactual import get_multidomain_cf

    ctx = await _load_ctx(req.job_id, req.org_id, db)
    engine = get_multidomain_cf(**ctx)

    try:
        result = engine.analyze_tech_investment(
            one_time_invest_try=req.one_time_invest_try,
            monthly_ops_increase_try=req.monthly_ops_increase_try,
            velocity_gain_pct=req.velocity_gain_pct,
            horizon_months=req.horizon_months,
        )
    except Exception as exc:
        logger.exception("Tech MD CF hatasi: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    return result.to_dict()


@router.get("/multidomain-cf/actions")
async def list_actions(
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Desteklenen multi-domain aksiyon listesi ve parametreleri."""
    return {
        "actions": [
            {
                "type":        "headcount_change",
                "label":       "Personel Degisimi",
                "endpoint":    "/multidomain-cf/headcount",
                "description": "Ise alim veya kadro azaltiminin CFO+CHRO+CTO+CMO uzerindeki birlesik etkisi",
                "domains":     ["cfo", "chro", "cto", "cmo"],
                "params": [
                    {"name": "delta",                   "type": "int",    "label": "Kisi (+ise al/-cikar)"},
                    {"name": "avg_monthly_salary_try",  "type": "float",  "label": "Ortalama Maas (TRY/ay)", "optional": True},
                    {"name": "role_type",               "type": "select", "label": "Rol Tipi", "options": ["engineer", "sales", "ops", "general"]},
                    {"name": "onboarding_months",       "type": "int",    "label": "Onboarding Suresi (ay)", "default": 2},
                    {"name": "horizon_months",          "type": "int",    "label": "Analiz Ufku (ay)",       "default": 12},
                ],
            },
            {
                "type":        "marketing_investment",
                "label":       "Pazarlama Yatirimi",
                "endpoint":    "/multidomain-cf/marketing",
                "description": "Pazarlama butcesi artisinin CFO+CMO+COO uzerindeki birlesik etkisi",
                "domains":     ["cfo", "cmo", "coo"],
                "params": [
                    {"name": "monthly_increase_try", "type": "float", "label": "Aylik Ek Butce (TRY)"},
                    {"name": "expected_roas",        "type": "float", "label": "Hedef ROAS",          "default": 2.5},
                    {"name": "horizon_months",       "type": "int",   "label": "Analiz Ufku (ay)",    "default": 12},
                ],
            },
            {
                "type":        "tech_investment",
                "label":       "Teknoloji Yatirimi",
                "endpoint":    "/multidomain-cf/tech",
                "description": "Teknoloji/altyapi yatiriminin CFO+CTO+COO uzerindeki birlesik etkisi",
                "domains":     ["cfo", "cto", "coo"],
                "params": [
                    {"name": "one_time_invest_try",      "type": "float", "label": "One-time Yatirim (TRY)"},
                    {"name": "monthly_ops_increase_try", "type": "float", "label": "Aylik Ops Artisi (TRY)", "default": 0},
                    {"name": "velocity_gain_pct",        "type": "float", "label": "Beklenen Velocity Artisi (0-1)", "default": 0.15},
                    {"name": "horizon_months",           "type": "int",   "label": "Analiz Ufku (ay)",              "default": 12},
                ],
            },
        ]
    }
