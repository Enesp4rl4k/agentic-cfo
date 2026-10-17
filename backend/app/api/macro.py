"""
TCMB Macroeconomic Indicators & Stress Testing API — /api/v1/macro.

Endpoints:
  GET  /macro/tcmb     → Live/cached macroeconomic snapshot from TCMB EVDS (USD/TRY, EUR/TRY, Policy Rate, Inflation)
  POST /macro/simulate → Stress testing simulation under FX and interest rate shock scenarios
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.services.company_context import get_company_context
from app.services.tcmb_macro import TCMBMacroService

router = APIRouter(prefix="/macro", tags=["macro"])
logger = logging.getLogger(__name__)


class MacroSimulationRequest(BaseModel):
    usd_shock_pct: float = Field(default=15.0, ge=-50.0, le=200.0, description="Beklenen USD/TRY % değişimi")
    eur_shock_pct: float = Field(default=15.0, ge=-50.0, le=200.0, description="Beklenen EUR/TRY % değişimi")
    interest_rate_delta_bp: float = Field(default=500.0, ge=-3000.0, le=5000.0, description="Faiz değişimi (baz puan, 500 = %5)")
    payment_delay_days: int = Field(default=15, ge=0, le=180, description="Alacak tahsilat gecikmesi (gün)")


@router.get("/tcmb")
async def get_tcmb_indicators(
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Get live or cached macroeconomic snapshot from TCMB EVDS.
    Includes USD/TRY, EUR/TRY, Policy Rate, Inflation (CPI/PPI) and real cost of capital.
    """
    svc = TCMBMacroService()
    try:
        snapshot = await svc.get_macro_snapshot()
        return {"data": snapshot.to_dict(), "error": None}
    except Exception as exc:
        logger.exception("Failed to retrieve TCMB macro snapshot: %s", exc)
        raise HTTPException(status_code=500, detail="Makroekonomik veriler alınamadı") from exc


@router.post("/simulate")
async def simulate_macro_shock(
    body: MacroSimulationRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Simulate financial stress testing under macroeconomic shock scenarios.
    Calculates runway impact, incremental cost of capital, and liquidity risk.
    """
    org_id = str(current_user.org_id) if current_user.org_id else f"user:{current_user.id}"
    ctx = await get_company_context(org_id, db)
    macro_svc = TCMBMacroService()
    macro = await macro_svc.get_macro_snapshot()

    cfo_res = ctx.last_cfo_result or {}
    pnl = cfo_res.get("pnl") or {}
    forecast = cfo_res.get("forecast") or {}
    base_scenario = (forecast.get("scenarios") or {}).get("base") or {}

    # Extract baseline financials (integer cents / kuruş)
    base_runway = float(base_scenario.get("runway_months") or 12.0)
    monthly_opex_cents = int((pnl.get("total_opex") or 10_000_000) if isinstance(pnl.get("total_opex"), (int, float)) else 10_000_000)
    revenue_cents = int((pnl.get("revenue") or 15_000_000) if isinstance(pnl.get("revenue"), (int, float)) else 15_000_000)

    # 1. FX Shock calculation: Estimate 25% of opex has USD/EUR exposure (cloud, licenses, imports)
    fx_exposure_ratio = 0.25
    blended_fx_shock = (body.usd_shock_pct + body.eur_shock_pct) / 2.0
    additional_fx_opex_cents = int(monthly_opex_cents * fx_exposure_ratio * (blended_fx_shock / 100.0))

    # 2. Interest rate shock: Impact on working capital financing (approx 2 months opex as debt)
    rate_delta_pct = body.interest_rate_delta_bp / 100.0  # 500 bp = 5.0%
    working_capital_debt_cents = monthly_opex_cents * 2
    additional_monthly_interest_cents = int((working_capital_debt_cents * (rate_delta_pct / 100.0)) / 12.0)

    # 3. Working capital delay drag: 15 days delay freezes cash flow
    delay_drag_pct = min(0.30, (body.payment_delay_days / 30.0) * 0.10)
    delayed_revenue_impact_cents = int(revenue_cents * delay_drag_pct)

    # Total stressed monthly burn increase (FX + borrowing cost + working capital drag amortized)
    total_monthly_burn_increase_cents = max(
        0,
        additional_fx_opex_cents
        + additional_monthly_interest_cents
        + int(delayed_revenue_impact_cents / 6.0),
    )

    # Stressed runway calculation
    burn_increase_ratio = total_monthly_burn_increase_cents / max(1, monthly_opex_cents)
    runway_contraction_factor = max(0.20, 1.0 - (burn_increase_ratio * 1.5))
    stressed_runway = round(base_runway * runway_contraction_factor, 1)
    runway_delta = round(stressed_runway - base_runway, 1)

    # Risk level categorization
    if stressed_runway < 3.0:
        risk_level = "CRITICAL"
        risk_label = "Kritik Nakit Riski"
        color = "red"
    elif stressed_runway < 6.0:
        risk_level = "HIGH"
        risk_label = "Yüksek Risk"
        color = "amber"
    elif stressed_runway < 12.0:
        risk_level = "MODERATE"
        risk_label = "Orta Seviye Risk"
        color = "blue"
    else:
        risk_level = "LOW"
        risk_label = "Düşük Risk"
        color = "green"

    # Actionable mitigation recommendations
    recommendations = []
    if body.usd_shock_pct > 10.0:
        recommendations.append("Döviz bazlı bulut (AWS/GCP/SaaS) sözleşmelerini yıllık TL bazlı taahhüde geçirmeyi müzakere edin.")
        recommendations.append("Döviz açık pozisyonunuz için forward veya vadeli işlem sözleşmesi (hedge) değerlendirin.")
    if body.interest_rate_delta_bp > 300.0:
        recommendations.append("Değişken faizli kredileri sabit faizliye çevirin veya erken kapama opsiyonunu inceleyin.")
    if body.payment_delay_days > 10:
        recommendations.append("Büyük müşterilere erken ödeme iskontosu (%2-3 nakit indirimi) sunarak tahsilat süresini kısaltın.")

    return {
        "data": {
            "current_macro": {
                "usd_try": macro.usd_try,
                "eur_try": macro.eur_try,
                "policy_rate_pct": macro.policy_rate_pct,
                "inflation_pct": macro.inflation_pct,
                "real_cost_of_capital": macro.real_cost_of_capital(),
            },
            "shock_inputs": {
                "usd_shock_pct": body.usd_shock_pct,
                "eur_shock_pct": body.eur_shock_pct,
                "interest_rate_delta_bp": body.interest_rate_delta_bp,
                "payment_delay_days": body.payment_delay_days,
            },
            "simulation_result": {
                "baseline_runway_months": base_runway,
                "stressed_runway_months": stressed_runway,
                "runway_delta_months": runway_delta,
                "monthly_cost_increase_kurus": total_monthly_burn_increase_cents,
                "monthly_cost_increase_lira": round(total_monthly_burn_increase_cents / 100.0, 2),
                "additional_fx_cost_lira": round(additional_fx_opex_cents / 100.0, 2),
                "additional_interest_cost_lira": round(additional_monthly_interest_cents / 100.0, 2),
                "risk_level": risk_level,
                "risk_label": risk_label,
                "risk_color": color,
                "recommendations": recommendations,
            },
        },
        "error": None,
    }
