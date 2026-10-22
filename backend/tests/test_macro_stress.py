"""Pure stress-test model: units, EUR independence, and no invented baseline."""
from __future__ import annotations

from app.services.macro_stress import (
    ASSUMPTIONS,
    ShockInputs,
    StressBaseline,
    baseline_from_cfo,
    simulate,
)

# A 12-month dashboard: lira period totals, as report_agent persists them.
CFO_12M = {
    "pnl": {
        "revenue": 1_200_000.0,      # ₺100k / month
        "total_opex": 600_000.0,     # ₺50k / month
        "net_income": -120_000.0,    # ₺-10k / month
    },
    "cashflow": {"monthly_series": [{}] * 12},
    "forecast": {"scenarios": {"base": {"runway_months": 8}}},
}

NO_SHOCK = ShockInputs(0, 0, 0, 0)


def _base(**kw) -> StressBaseline:
    b = baseline_from_cfo(CFO_12M)
    assert b is not None
    return StressBaseline(**{**b.__dict__, **kw})


# ── baseline ──────────────────────────────────────────────────────────────────


def test_baseline_turns_lira_period_totals_into_monthly_kurus():
    b = baseline_from_cfo(CFO_12M)
    assert b is not None
    assert b.monthly_revenue_kurus == 10_000_000   # ₺100k
    assert b.monthly_opex_kurus == 5_000_000       # ₺50k
    assert b.monthly_net_kurus == -1_000_000       # ₺-10k
    assert b.months_observed == 12
    assert b.runway_months == 8.0


def test_baseline_reads_the_persisted_dashboard_opex_by_category():
    """report_agent persists ``opex`` per category, never ``total_opex`` — the
    old endpoint therefore fell back to an invented ₺100k for every real org."""
    dashboard_shape = {
        **CFO_12M,
        "pnl": {
            "revenue": 1_200_000.0,
            "net_income": -120_000.0,
            "opex": {"salary": 360_000.0, "rent": 120_000.0, "technology": 120_000.0},
        },
    }
    b = baseline_from_cfo(dashboard_shape)
    assert b is not None
    assert b.monthly_opex_kurus == 5_000_000  # ₺600k / 12


def test_no_cfo_analysis_means_no_baseline_not_an_invented_company():
    assert baseline_from_cfo(None) is None
    assert baseline_from_cfo({}) is None
    assert baseline_from_cfo({"pnl": {"revenue": 1.0}}) is None  # no opex
    no_months = {**CFO_12M, "cashflow": {"monthly_series": []}}
    assert baseline_from_cfo(no_months) is None


def test_profitable_forecast_keeps_runway_unbounded():
    cfo = {**CFO_12M, "forecast": {"scenarios": {"base": {"runway_months": None}}}}
    b = baseline_from_cfo(cfo)
    assert b is not None
    assert b.runway_months is None


# ── simulate ──────────────────────────────────────────────────────────────────


def test_fx_cost_is_lira_scale_not_100x_smaller():
    """₺50k/month opex, 25% exposed, +20% on both currencies → ₺2.500/month."""
    out = simulate(ShockInputs(20, 20, 0, 0), _base())
    assert out["additional_fx_cost_lira"] == 2_500.0
    assert out["monthly_cost_increase_kurus"] == 250_000


def test_eur_shock_moves_the_result_independently_of_usd():
    usd_only = simulate(ShockInputs(20, 0, 0, 0), _base())
    both = simulate(ShockInputs(20, 20, 0, 0), _base())
    assert usd_only["additional_fx_cost_lira"] == 1_250.0
    assert both["additional_fx_cost_lira"] == 2_500.0


def test_interest_and_delay_components():
    out = simulate(ShockInputs(0, 0, 600, 30), _base())
    # 2 months opex (₺100k) × 6% / 12 = ₺500
    assert out["additional_interest_cost_lira"] == 500.0
    # ₺100k revenue × 10% drag / 6 months = ₺1.666,66
    assert out["additional_delay_cost_lira"] == 1_666.66


def test_shock_contracts_runway_and_no_shock_leaves_it():
    calm = simulate(NO_SHOCK, _base())
    assert calm["stressed_runway_months"] == 8.0
    assert calm["runway_delta_months"] == 0.0

    hit = simulate(ShockInputs(40, 40, 1500, 45), _base())
    assert hit["stressed_runway_months"] < 8.0
    assert hit["runway_delta_months"] < 0


def test_unbounded_runway_reports_cash_turn_not_a_month_count():
    profitable = _base(runway_months=None, monthly_net_kurus=100_000)  # ₺1k/month surplus
    small = simulate(ShockInputs(0, 0, 0, 0), profitable)
    assert small["stressed_runway_months"] is None
    assert small["risk_level"] == "LOW"

    big = simulate(ShockInputs(50, 50, 0, 0), profitable)  # +₺6.250 > ₺1k surplus
    assert big["stressed_runway_months"] is None
    assert big["risk_level"] == "CASH_NEGATIVE"
    assert big["monthly_net_after_shock_lira"] < 0


def test_output_is_labelled_estimate_with_its_assumptions():
    out = simulate(NO_SHOCK, _base())
    assert out["data_source"] == "estimated"
    assert out["assumptions"] == ASSUMPTIONS


def test_recommendations_are_codes_for_the_ui_to_word():
    out = simulate(ShockInputs(0, 25, 400, 20), _base())
    assert out["recommendations"] == [
        "fx_contracts_to_try",
        "fx_hedge",
        "fixed_rate_loans",
        "early_payment_discount",
    ]
