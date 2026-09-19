"""
Counterfactual API — S6

POST /counterfactual/simulate — "Ne olurdu?" simülasyonu

Endpoint'ler:
  POST /counterfactual/simulate/headcount   — Personel değişimi
  POST /counterfactual/simulate/cost        — Maliyet kesintisi
  POST /counterfactual/simulate/price       — Fiyat artışı
  GET  /counterfactual/scenarios/{job_id}   — Job'a özgü hazır senaryolar
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.access import load_owned_job, owned_job
from app.api.auth import get_current_user
from app.database import get_db
from app.models.analysis_job import AnalysisJob
from app.models.user import User

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Request şemaları ──────────────────────────────────────────────────────────

class HeadcountSimRequest(BaseModel):
    job_id: str
    delta: int = Field(..., description="Pozitif = işe al, negatif = çıkar")
    avg_monthly_salary_try: float = Field(..., gt=0, description="Brüt aylık maaş (TRY)")
    productivity_gain_pct: float = Field(0.10, ge=0, le=1.0)
    onboarding_months: int = Field(2, ge=0, le=6)
    horizon_months: int = Field(12, ge=1, le=36)


class CostReductionSimRequest(BaseModel):
    job_id: str
    target_category: str = Field(..., description="salary|rent|marketing|technology|utilities")
    reduction_pct: float = Field(..., gt=0, le=1.0)
    one_time_cost_try: float = Field(0.0, ge=0)
    horizon_months: int = Field(12, ge=1, le=36)


class PriceIncreaseSimRequest(BaseModel):
    job_id: str
    increase_pct: float = Field(..., gt=0, le=1.0)
    churn_rate_increase: float = Field(0.05, ge=0, le=0.5)
    horizon_months: int = Field(12, ge=1, le=36)


# ── Helpers ────────────────────────────────────────────────────────────────────

async def _load_pnl_cashflow_forecast(job_id: str, db: AsyncSession) -> tuple[dict, dict, dict]:
    """Load P&L, cashflow, forecast from the latest JSON report for a job."""
    from app.models.report import Report, ReportFormat
    result = await db.execute(
        select(Report)
        .where(Report.job_id == job_id, Report.report_format == ReportFormat.JSON)
        .order_by(desc(Report.created_at))
        .limit(1)
    )
    rep = result.scalar_one_or_none()
    if not rep or not rep.data:
        return {}, {}, {}

    d = rep.data
    return d.get("pnl") or {}, d.get("cashflow") or {}, d.get("forecast") or {}


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/counterfactual/simulate/headcount")
async def simulate_headcount(
    body: HeadcountSimRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    S6-2: Personel artırımı/azaltımı simülasyonu.

    Verilen iş analizi sonuçlarını kullanarak:
    - Net gelir etkisi (12 ay)
    - Break-even süresi
    - 3 senaryo (iyimser/baz/kötümser)
    - Cashflow risk değerlendirmesi
    """
    # A job id from the request body, loaded without asking whose it was.
    if body.job_id:
        await load_owned_job(db, body.job_id, current_user)
    pnl, cashflow, forecast = await _load_pnl_cashflow_forecast(body.job_id, db)
    if not pnl:
        raise HTTPException(
            status_code=404,
            detail="Bu job için P&L verisi bulunamadı. Önce analizi tamamlayın.",
        )

    from app.services.counterfactual_engine import CounterfactualEngine
    engine = CounterfactualEngine(pnl=pnl, cashflow=cashflow, forecast=forecast)

    result = engine.simulate_headcount_change(
        delta=body.delta,
        avg_monthly_salary_try=body.avg_monthly_salary_try,
        productivity_gain_pct=body.productivity_gain_pct,
        onboarding_months=body.onboarding_months,
        horizon_months=body.horizon_months,
    )

    logger.info(
        "Counterfactual headcount: job=%s delta=%+d net_impact=₺%,.0f",
        body.job_id, body.delta, result.base_net_impact,
    )

    return {"data": result.to_dict(), "error": None}


@router.post("/counterfactual/simulate/cost")
async def simulate_cost_reduction(
    body: CostReductionSimRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    S6-3: Maliyet kesintisi simülasyonu.

    Belirli bir gider kategorisinde kesinti yapıldığında:
    - 12 aylık tasarruf
    - Break-even (geçiş maliyeti varsa)
    - Cashflow etkisi
    """
    # A job id from the request body, loaded without asking whose it was.
    if body.job_id:
        await load_owned_job(db, body.job_id, current_user)
    pnl, cashflow, forecast = await _load_pnl_cashflow_forecast(body.job_id, db)
    if not pnl:
        raise HTTPException(
            status_code=404,
            detail="Bu job için P&L verisi bulunamadı.",
        )

    from app.services.counterfactual_engine import CounterfactualEngine
    engine = CounterfactualEngine(pnl=pnl, cashflow=cashflow, forecast=forecast)

    result = engine.simulate_cost_reduction(
        target_category=body.target_category,
        reduction_pct=body.reduction_pct,
        one_time_cost_try=body.one_time_cost_try,
        horizon_months=body.horizon_months,
    )

    logger.info(
        "Counterfactual cost: job=%s cat=%s pct=%.0f%% saving=₺%,.0f",
        body.job_id, body.target_category, body.reduction_pct * 100, result.base_net_impact,
    )

    return {"data": result.to_dict(), "error": None}


@router.post("/counterfactual/simulate/price")
async def simulate_price_increase(
    body: PriceIncreaseSimRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Fiyat artışı simülasyonu — gelir artışı vs. churn dengesi."""
    # A job id from the request body, loaded without asking whose it was.
    if body.job_id:
        await load_owned_job(db, body.job_id, current_user)
    pnl, cashflow, forecast = await _load_pnl_cashflow_forecast(body.job_id, db)
    if not pnl:
        raise HTTPException(status_code=404, detail="P&L verisi bulunamadı.")

    from app.services.counterfactual_engine import CounterfactualEngine
    engine = CounterfactualEngine(pnl=pnl, cashflow=cashflow, forecast=forecast)

    result = engine.simulate_price_increase(
        increase_pct=body.increase_pct,
        churn_rate_increase=body.churn_rate_increase,
        horizon_months=body.horizon_months,
    )

    return {"data": result.to_dict(), "error": None}


@router.get("/counterfactual/scenarios/{job_id}")
async def get_preset_scenarios(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    job: AnalysisJob = Depends(owned_job),
) -> dict[str, Any]:
    """
    Job'a özgü hazır "ne olurdu?" senaryoları.

    Şirketin mevcut verisine göre anlamlı senaryoları otomatik önerir:
    - Mevcut maaş ortalamasıyla 2 kişi işe alma
    - En büyük gider kategorisinde %20 kesinti
    - %10 fiyat artışı
    """
    pnl, cashflow, forecast = await _load_pnl_cashflow_forecast(job_id, db)
    if not pnl:
        raise HTTPException(status_code=404, detail="P&L verisi bulunamadı.")

    from app.services.counterfactual_engine import CounterfactualEngine
    engine = CounterfactualEngine(pnl=pnl, cashflow=cashflow, forecast=forecast)

    # Ortalama maaş tahmini — salary opex'ten
    monthly_salary_total = (pnl.get("opex", {}).get("salary", 0) or 0) / 100 / 12
    headcount_est = max(1, round(engine.monthly_opex * 0.4 / 30000))  # kaba tahmin
    avg_salary = monthly_salary_total / headcount_est if headcount_est > 0 else 50000

    # En büyük gider kategorisi
    opex = pnl.get("opex") or {}
    top_cat = max(opex, key=lambda k: opex[k]) if opex else "rent"

    scenarios = []

    # Senaryo 1: 2 kişi işe al
    try:
        s1 = engine.simulate_headcount_change(delta=2, avg_monthly_salary_try=max(avg_salary, 20000))
        scenarios.append({"label": "2 Kişi İşe Alma", **s1.to_dict()})
    except Exception:
        pass

    # Senaryo 2: En büyük kalemde %20 kesinti
    try:
        s2 = engine.simulate_cost_reduction(target_category=top_cat, reduction_pct=0.20)
        scenarios.append({"label": f"{top_cat.title()} %20 Kesinti", **s2.to_dict()})
    except Exception:
        pass

    # Senaryo 3: %10 fiyat artışı
    try:
        s3 = engine.simulate_price_increase(increase_pct=0.10)
        scenarios.append({"label": "%10 Fiyat Artışı", **s3.to_dict()})
    except Exception:
        pass

    return {
        "data": {
            "job_id":    job_id,
            "scenarios": scenarios,
        },
        "error": None,
    }
