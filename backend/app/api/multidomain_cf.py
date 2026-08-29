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
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

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
    """
    Load CF baselines. Prefer semantic snapshot metrics, then CompanyContext
    last_*_result, then job Report JSON.
    """
    resolved_org = org_id
    out: dict[str, Any] = {}

    if resolved_org:
        try:
            from app.services.company_context import get_company_context
            from app.services.semantic.store import get_latest_semantic_snapshot

            snap = await get_latest_semantic_snapshot(str(resolved_org), db)
            ctx = await get_company_context(str(resolved_org), db)
            cfo = ctx.last_cfo_result or {}
            dash = cfo.get("dashboard") or cfo
            pnl = dict(dash.get("pnl") or {})
            cashflow = dict(dash.get("cashflow") or {})
            forecast = dict(dash.get("forecast") or {})

            if snap is not None:
                vals = snap.values()
                # Inject semantic baselines into pnl/cashflow/forecast shapes CF engines expect
                if vals.get("finance.revenue") is not None and "revenue" not in pnl:
                    pnl["revenue"] = vals["finance.revenue"]
                    pnl["revenue_cents"] = vals["finance.revenue"]
                if vals.get("finance.net_margin") is not None:
                    pnl["net_margin"] = vals["finance.net_margin"]
                if vals.get("finance.operating_cashflow") is not None:
                    cashflow["operating"] = vals["finance.operating_cashflow"]
                    cashflow["operating_cents"] = vals["finance.operating_cashflow"]
                if vals.get("finance.runway_months") is not None:
                    scenarios = dict(forecast.get("scenarios") or {})
                    base = dict(scenarios.get("base") or {})
                    base["runway_months"] = vals["finance.runway_months"]
                    scenarios["base"] = base
                    forecast["scenarios"] = scenarios
                out["semantic_metrics"] = vals
                out["semantic_period"] = snap.period.key
                out["semantic_currency"] = snap.currency

            out.update(
                {
                    "pnl": pnl,
                    "cashflow": cashflow,
                    "forecast": forecast,
                    "chro_data": ctx.last_chro_result or {},
                    "cto_data": ctx.last_cto_result or {},
                    "cmo_data": ctx.last_cmo_result or {},
                    "coo_data": ctx.last_coo_result or {},
                }
            )
            if out.get("pnl") or out.get("semantic_metrics"):
                return out
        except Exception as exc:
            logger.debug("Semantic/context CF baseline failed: %s", exc)

    if job_id:
        from app.models.report import Report, ReportFormat  # type: ignore[attr-defined]
        stmt = (
            select(Report)
            .where(Report.job_id == job_id, Report.format == ReportFormat.JSON)
            .order_by(desc(Report.created_at))
            .limit(1)
        )
        row = (await db.execute(stmt)).scalar_one_or_none()
        raw = None
        if row is not None:
            raw = getattr(row, "data", None) or getattr(row, "content", None)
        if raw:
            try:
                import json
                data = json.loads(raw) if isinstance(raw, str) else raw
                return {
                    "pnl": data.get("pnl") or {},
                    "cashflow": data.get("cashflow") or {},
                    "forecast": data.get("forecast") or {},
                }
            except Exception:
                pass

    return out


async def _attach_cf_to_brief(
    org_id: str | None,
    cf_action: str,
    db: AsyncSession,
) -> None:
    """Persist linked_cf_action hint onto decision brief options after a what-if run."""
    if not org_id:
        return
    try:
        from app.services.semantic.rebuild import rebuild_semantic_snapshot
        from app.services.semantic.store import get_latest_semantic_snapshot, save_semantic_snapshot

        snap = await rebuild_semantic_snapshot(str(org_id), db, include_brief=True)
        if snap is None or snap.brief is None:
            snap = await get_latest_semantic_snapshot(str(org_id), db)
        if snap is None or snap.brief is None:
            return
        for opt in snap.brief.options:
            if opt.linked_cf_action == cf_action:
                opt.impact_summary = f"{opt.impact_summary} (last what-if: {cf_action})"
        await save_semantic_snapshot(snap, db)
    except Exception as exc:
        logger.debug("attach CF to brief skipped: %s", exc)


def _cf_engine_kwargs(ctx: dict[str, Any]) -> dict[str, Any]:
    keys = ("pnl", "cashflow", "forecast", "chro_data", "cto_data", "cmo_data", "coo_data")
    return {k: ctx[k] for k in keys if k in ctx}


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

    org = req.org_id or (str(current_user.org_id) if current_user.org_id else None)
    ctx = await _load_ctx(req.job_id, org, db)
    engine = get_multidomain_cf(**_cf_engine_kwargs(ctx))

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

    await _attach_cf_to_brief(org, "headcount_change", db)
    payload = result.to_dict()
    payload["baseline_source"] = "semantic" if ctx.get("semantic_metrics") else "context"
    return payload


@router.post("/multidomain-cf/marketing")
async def multidomain_marketing(
    req: MarketingMDRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Pazarlama yatiriminin CFO + CMO + COO uzerindeki birlesik etkisi."""
    from app.services.multidomain_counterfactual import get_multidomain_cf

    org = req.org_id or (str(current_user.org_id) if current_user.org_id else None)
    ctx = await _load_ctx(req.job_id, org, db)
    engine = get_multidomain_cf(**_cf_engine_kwargs(ctx))

    try:
        result = engine.analyze_marketing_investment(
            monthly_increase_try=req.monthly_increase_try,
            expected_roas=req.expected_roas,
            horizon_months=req.horizon_months,
        )
    except Exception as exc:
        logger.exception("Marketing MD CF hatasi: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    await _attach_cf_to_brief(org, "marketing_invest", db)
    payload = result.to_dict()
    payload["baseline_source"] = "semantic" if ctx.get("semantic_metrics") else "context"
    return payload


@router.post("/multidomain-cf/tech")
async def multidomain_tech(
    req: TechInvestMDRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Teknoloji yatiriminin CFO + CTO + COO uzerindeki birlesik etkisi."""
    from app.services.multidomain_counterfactual import get_multidomain_cf

    org = req.org_id or (str(current_user.org_id) if current_user.org_id else None)
    ctx = await _load_ctx(req.job_id, org, db)
    engine = get_multidomain_cf(**_cf_engine_kwargs(ctx))

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

    await _attach_cf_to_brief(org, "tech_investment", db)
    payload = result.to_dict()
    payload["baseline_source"] = "semantic" if ctx.get("semantic_metrics") else "context"
    return payload


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
