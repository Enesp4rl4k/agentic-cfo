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
from app.services.macro_stress import ShockInputs, baseline_from_cfo, simulate
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

    shock = ShockInputs(
        usd_shock_pct=body.usd_shock_pct,
        eur_shock_pct=body.eur_shock_pct,
        interest_rate_delta_bp=body.interest_rate_delta_bp,
        payment_delay_days=body.payment_delay_days,
    )
    # Baseline only from the org's own CFO analysis — no analysis, no result
    # (never an invented company presented as the user's).
    baseline = baseline_from_cfo(ctx.last_cfo_result)
    simulation = simulate(shock, baseline) if baseline is not None else None

    return {
        "data": {
            "current_macro": {
                "usd_try": macro.usd_try,
                "eur_try": macro.eur_try,
                "policy_rate_pct": macro.policy_rate_pct,
                "inflation_pct": macro.inflation_pct,
                "real_cost_of_capital": macro.real_cost_of_capital(),
                "data_source": macro.data_source,
            },
            "shock_inputs": {
                "usd_shock_pct": body.usd_shock_pct,
                "eur_shock_pct": body.eur_shock_pct,
                "interest_rate_delta_bp": body.interest_rate_delta_bp,
                "payment_delay_days": body.payment_delay_days,
            },
            "simulation_result": simulation,
            "baseline_missing_reason": None if baseline is not None else "no_cfo_analysis",
        },
        "error": None,
    }
