"""What-If Monte Carlo Simulation API (Plan v12 Faz 3)."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.services.cash_radar import compute_cash_radar
from app.services.monte_carlo import ScenarioParam, run_monte_carlo_simulation

router = APIRouter(prefix="/simulation", tags=["simulation"])


class ScenarioItem(BaseModel):
    scenario_type: Literal["hire_headcount", "defer_payable", "revenue_shock", "capex_investment"]
    headcount: int = 1
    net_monthly_salary_cents: int = 0
    start_week: int = 1
    amount_cents: int = 0
    from_week: int = 1
    to_week: int = 5
    percentage_change: float = 0.0
    delay_days: int = 0
    target_week: int = 1


class WhatIfRequest(BaseModel):
    scenarios: list[ScenarioItem] = Field(default_factory=list)
    iterations: int = Field(default=5000, ge=100, le=20000)


def _org(user: User) -> str:
    if not user.org_id:
        raise HTTPException(400, "Bu işlem için bir organizasyon gerekli.")
    return str(user.org_id)


@router.post("/what-if")
async def simulate_what_if(
    body: WhatIfRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Run parametric Monte Carlo simulation over current organization's 13-week Cash Radar."""
    org_id = _org(user)
    radar = await compute_cash_radar(db, org_id)

    scenario_params = [
        ScenarioParam(
            scenario_type=s.scenario_type,
            headcount=s.headcount,
            net_monthly_salary_cents=s.net_monthly_salary_cents,
            start_week=s.start_week,
            amount_cents=s.amount_cents,
            from_week=s.from_week,
            to_week=s.to_week,
            percentage_change=s.percentage_change,
            delay_days=s.delay_days,
            target_week=s.target_week,
        )
        for s in body.scenarios
    ]

    result = run_monte_carlo_simulation(
        baseline_weeks=[asdict(w) for w in radar.weeks],
        starting_cash_cents=radar.starting_cash_cents or 0,
        scenarios=scenario_params,
        iterations=body.iterations,
    )

    return {
        "data": {
            "starting_cash_cents": radar.starting_cash_cents,
            "simulated": result.to_dict(),
            "scenarios": [s.to_dict() for s in scenario_params],
        },
        "error": None,
    }
