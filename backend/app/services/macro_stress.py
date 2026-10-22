"""FX / interest / collection-delay stress test — pure, deterministic, testable.

``POST /macro/simulate`` used to compute this inline, with three honesty bugs:

- the dashboard ``pnl`` scalars are **lira period totals** (report_agent
  boundary — the same fact ``semantic.projectors`` converts), but they were read
  as monthly kuruş, so every lira output came back 100× too small and the
  "monthly" opex was the whole period's;
- with no CFO analysis it invented a company (runway 12, opex ₺100k, revenue
  ₺150k) and showed the result as if it were the user's;
- a profitable company (forecast never goes cash-negative → ``runway_months``
  is ``None``) was shown a 12-month runway.

Here the baseline comes only from the org's own CFO result
(:func:`baseline_from_cfo` returns ``None`` when there is none), money is kuruş
integers inside, and every modelling constant is surfaced in
:data:`ASSUMPTIONS` so the UI can label the output as an estimate.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Modelling assumptions — rule-based, not measured. Returned with every result.
FX_EXPOSURE_RATIO = 0.25       # share of opex priced in USD/EUR (cloud, licences, imports)
FX_USD_SHARE = 0.5             # split of that exposure between USD and EUR
WC_DEBT_MONTHS = 2             # working-capital debt ≈ this many months of opex
DELAY_DRAG_PER_30_DAYS = 0.10  # share of monthly revenue frozen per 30 days of delay
DELAY_DRAG_CAP = 0.30
DELAY_AMORTIZE_MONTHS = 6      # frozen revenue spread over this many months
RUNWAY_ELASTICITY = 1.5        # runway shrink per unit of burn increase / opex
RUNWAY_FLOOR = 0.20            # runway never contracts below this share

ASSUMPTIONS: dict[str, float] = {
    "fx_exposure_ratio": FX_EXPOSURE_RATIO,
    "fx_usd_share": FX_USD_SHARE,
    "working_capital_debt_months": WC_DEBT_MONTHS,
    "delay_drag_per_30_days": DELAY_DRAG_PER_30_DAYS,
    "delay_drag_cap": DELAY_DRAG_CAP,
    "delay_amortize_months": DELAY_AMORTIZE_MONTHS,
    "runway_elasticity": RUNWAY_ELASTICITY,
    "runway_floor": RUNWAY_FLOOR,
}


@dataclass(frozen=True)
class ShockInputs:
    usd_shock_pct: float
    eur_shock_pct: float
    interest_rate_delta_bp: float
    payment_delay_days: int


@dataclass(frozen=True)
class StressBaseline:
    """Monthly figures (kuruş) derived from the org's own CFO analysis."""

    monthly_opex_kurus: int
    monthly_revenue_kurus: int
    monthly_net_kurus: int
    months_observed: int
    # ``None`` = the forecast never goes cash-negative (no runway limit).
    runway_months: float | None


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _lira_to_kurus(lira: float) -> int:
    return round(lira * 100)


def baseline_from_cfo(cfo_result: dict[str, Any] | None) -> StressBaseline | None:
    """Monthly baseline from ``last_cfo_result`` (dashboard shape, lira totals).

    Returns ``None`` — never a made-up company — when the analysis is missing,
    has no revenue/opex figures, or no monthly series to turn totals into months.
    """
    if not cfo_result:
        return None
    pnl = cfo_result.get("pnl") or {}
    cashflow = cfo_result.get("cashflow") or {}
    forecast = cfo_result.get("forecast") or {}

    revenue = _num(pnl.get("revenue"))
    # The persisted dashboard carries opex by category (report_agent), not a
    # total; ``total_opex`` is the pnl_agent shape. Accept either.
    opex = _num(pnl.get("total_opex"))
    if opex is None and isinstance(pnl.get("opex"), dict):
        parts = [_num(v) for v in pnl["opex"].values()]
        if parts and all(p is not None for p in parts):
            opex = sum(p for p in parts if p is not None)
    if revenue is None or opex is None:
        return None
    months = len(cashflow.get("monthly_series") or [])
    if months <= 0:
        return None
    net = _num(pnl.get("net_income"))
    if net is None:
        net = revenue - (_num(pnl.get("total_expenses")) or opex)

    base = (forecast.get("scenarios") or {}).get("base") or {}
    runway = _num(base.get("runway_months"))

    return StressBaseline(
        monthly_opex_kurus=_lira_to_kurus(opex / months),
        monthly_revenue_kurus=_lira_to_kurus(revenue / months),
        monthly_net_kurus=_lira_to_kurus(net / months),
        months_observed=months,
        runway_months=runway,
    )


def _risk_level(stressed_runway: float) -> str:
    if stressed_runway < 3.0:
        return "CRITICAL"
    if stressed_runway < 6.0:
        return "HIGH"
    if stressed_runway < 12.0:
        return "MODERATE"
    return "LOW"


def recommendation_codes(shock: ShockInputs) -> list[str]:
    """Mitigation codes; the UI owns the wording (tr/en)."""
    codes: list[str] = []
    if max(shock.usd_shock_pct, shock.eur_shock_pct) > 10.0:
        codes += ["fx_contracts_to_try", "fx_hedge"]
    if shock.interest_rate_delta_bp > 300.0:
        codes.append("fixed_rate_loans")
    if shock.payment_delay_days > 10:
        codes.append("early_payment_discount")
    return codes


def simulate(shock: ShockInputs, baseline: StressBaseline) -> dict[str, Any]:
    """Stressed monthly cost and runway for one shock scenario."""
    opex = baseline.monthly_opex_kurus

    # 1. FX: the exposed share of opex reprices with each currency's shock.
    blended_fx_pct = (
        shock.usd_shock_pct * FX_USD_SHARE + shock.eur_shock_pct * (1 - FX_USD_SHARE)
    )
    fx_kurus = int(opex * FX_EXPOSURE_RATIO * blended_fx_pct / 100.0)

    # 2. Interest: annual rate delta on working-capital debt, per month.
    rate_delta_pct = shock.interest_rate_delta_bp / 100.0
    interest_kurus = int(opex * WC_DEBT_MONTHS * rate_delta_pct / 100.0 / 12.0)

    # 3. Collection delay: frozen revenue, amortised.
    drag = min(DELAY_DRAG_CAP, shock.payment_delay_days / 30.0 * DELAY_DRAG_PER_30_DAYS)
    delay_kurus = int(baseline.monthly_revenue_kurus * drag / DELAY_AMORTIZE_MONTHS)

    increase = max(0, fx_kurus + interest_kurus + delay_kurus)
    net_after = baseline.monthly_net_kurus - increase

    if baseline.runway_months is None:
        # No runway limit in the forecast: say whether the shock breaks that,
        # without inventing a month count we cannot know (no cash balance).
        stressed_runway = None
        runway_delta = None
        risk_level = "CASH_NEGATIVE" if net_after < 0 else "LOW"
    else:
        ratio = increase / max(1, opex)
        factor = max(RUNWAY_FLOOR, 1.0 - ratio * RUNWAY_ELASTICITY)
        stressed_runway = round(baseline.runway_months * factor, 1)
        runway_delta = round(stressed_runway - baseline.runway_months, 1)
        risk_level = _risk_level(stressed_runway)

    return {
        "baseline_runway_months": baseline.runway_months,
        "stressed_runway_months": stressed_runway,
        "runway_delta_months": runway_delta,
        "monthly_cost_increase_kurus": increase,
        "monthly_cost_increase_lira": round(increase / 100.0, 2),
        "additional_fx_cost_lira": round(fx_kurus / 100.0, 2),
        "additional_interest_cost_lira": round(interest_kurus / 100.0, 2),
        "additional_delay_cost_lira": round(delay_kurus / 100.0, 2),
        "monthly_net_after_shock_lira": round(net_after / 100.0, 2),
        "months_observed": baseline.months_observed,
        "risk_level": risk_level,
        "recommendations": recommendation_codes(shock),
        "data_source": "estimated",
        "assumptions": dict(ASSUMPTIONS),
    }
