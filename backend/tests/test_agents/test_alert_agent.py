"""
Tests for alert_agent.py — pure alert builder functions (no LLM, no DB).
Covers: _check_profitability, _check_cashflow, _check_growth, _check_budget
and THRESHOLDS constants.
"""
import pytest
from app.agents.alert_agent import (
    _check_profitability,
    _check_cashflow,
    _check_growth,
    _check_budget,
    THRESHOLDS,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _pnl(gross_margin: float = 0.40, net_margin: float = 0.10,
         net_income: int = 100_000) -> dict:
    return {
        "gross_margin": gross_margin,
        "net_margin": net_margin,
        "net_income": net_income,
    }


def _cashflow(operating: int = 100_000, runway: int | None = None) -> dict:
    """Build a minimal cashflow dict with optional runway in base scenario."""
    forecast_scenarios = {}
    if runway is not None:
        forecast_scenarios = {"base": {"runway_months": runway}}
    return {
        "operating": operating,
        "net_change": operating,
        "monthly_series": [],
        "scenarios": forecast_scenarios,
    }


def _forecast(runway: int | None = None) -> dict:
    if runway is None:
        return {"scenarios": {"base": {"runway_months": None}}}
    return {"scenarios": {"base": {"runway_months": runway}}}


def _multi_period(rev_change_pct: float | None = None,
                  trend: str = "stable") -> dict:
    mom = None
    if rev_change_pct is not None:
        mom = {"revenue_change_pct": rev_change_pct}
    return {"mom": mom, "trend_direction": trend}


def _budget(total_var_pct: float = 0.0) -> dict:
    return {"total_variance_pct": total_var_pct, "over_budget_categories": []}


# ── _check_profitability ──────────────────────────────────────────────────────

class TestCheckProfitability:

    def test_healthy_pnl_no_alerts(self):
        alerts = _check_profitability(_pnl(gross_margin=0.50, net_margin=0.15))
        assert alerts == []

    def test_critical_gross_margin_triggers_critical_alert(self):
        pnl = _pnl(gross_margin=0.05)   # below 10%
        alerts = _check_profitability(pnl)
        levels = [a["severity"] for a in alerts if a["metric"] == "gross_margin_pct"]
        assert "critical" in levels

    def test_warning_gross_margin_triggers_warning(self):
        pnl = _pnl(gross_margin=0.15)   # 15% — below 20% but above 10%
        alerts = _check_profitability(pnl)
        levels = [a["severity"] for a in alerts if a["metric"] == "gross_margin_pct"]
        assert "warning" in levels

    def test_gross_margin_above_warning_threshold_no_alert(self):
        pnl = _pnl(gross_margin=0.25)
        alerts = _check_profitability(pnl)
        margin_alerts = [a for a in alerts if a["metric"] == "gross_margin_pct"]
        assert margin_alerts == []

    def test_negative_net_margin_critical_triggers(self):
        pnl = _pnl(net_margin=-0.10, net_income=-100_000)
        alerts = _check_profitability(pnl)
        margin_alerts = [a for a in alerts if a["metric"] == "net_margin_pct"]
        assert any(a["severity"] == "critical" for a in margin_alerts)

    def test_returns_list(self):
        alerts = _check_profitability(_pnl())
        assert isinstance(alerts, list)

    def test_alert_has_required_keys(self):
        pnl = _pnl(gross_margin=0.05)
        alerts = _check_profitability(pnl)
        for a in alerts:
            for key in ("type", "severity", "message", "metric"):
                assert key in a

    def test_alert_type_is_profitability(self):
        pnl = _pnl(gross_margin=0.05)
        alerts = _check_profitability(pnl)
        for a in alerts:
            assert a["type"] == "profitability"

    def test_empty_pnl_does_not_crash(self):
        alerts = _check_profitability({})
        assert isinstance(alerts, list)


# ── _check_cashflow ───────────────────────────────────────────────────────────

class TestCheckCashflow:

    def test_healthy_cashflow_no_alerts(self):
        alerts = _check_cashflow(
            {"operating": 500_000, "net_change": 200_000, "monthly_series": []},
            _forecast(runway=12)
        )
        assert alerts == []

    def test_negative_operating_cashflow_critical(self):
        cf = {"operating": -100_000, "net_change": -100_000, "monthly_series": []}
        alerts = _check_cashflow(cf, _forecast(None))
        liquidity = [a for a in alerts if a["type"] == "liquidity"]
        assert any(a["severity"] == "critical" for a in liquidity)

    def test_critical_runway_triggers_critical_alert(self):
        cf = {"operating": 100_000, "net_change": 100_000, "monthly_series": []}
        alerts = _check_cashflow(cf, _forecast(runway=1))  # 1 month!
        runway_alerts = [a for a in alerts if a["metric"] == "runway_months"]
        assert any(a["severity"] == "critical" for a in runway_alerts)

    def test_warning_runway_triggers_warning(self):
        cf = {"operating": 100_000, "net_change": 100_000, "monthly_series": []}
        alerts = _check_cashflow(cf, _forecast(runway=4))  # 4 months
        runway_alerts = [a for a in alerts if a["metric"] == "runway_months"]
        assert any(a["severity"] == "warning" for a in runway_alerts)

    def test_no_runway_alert_when_runway_is_none(self):
        cf = {"operating": 100_000, "net_change": 100_000, "monthly_series": []}
        alerts = _check_cashflow(cf, _forecast(runway=None))
        runway_alerts = [a for a in alerts if a["metric"] == "runway_months"]
        assert runway_alerts == []

    def test_returns_list(self):
        cf = {"operating": 100_000, "net_change": 100_000, "monthly_series": []}
        alerts = _check_cashflow(cf, _forecast(12))
        assert isinstance(alerts, list)

    def test_empty_inputs_do_not_crash(self):
        alerts = _check_cashflow({}, {})
        assert isinstance(alerts, list)


# ── _check_growth ─────────────────────────────────────────────────────────────

class TestCheckGrowth:

    def test_no_data_no_alerts(self):
        alerts = _check_growth(None)
        assert alerts == []

    def test_no_mom_no_alerts(self):
        alerts = _check_growth({"mom": None, "trend_direction": "stable"})
        assert alerts == []

    def test_critical_revenue_decline_triggers_critical(self):
        mp = _multi_period(rev_change_pct=-25.0)   # -25% < -20% threshold
        alerts = _check_growth(mp)
        rev_alerts = [a for a in alerts if a["metric"] == "revenue_mom_pct"]
        assert any(a["severity"] == "critical" for a in rev_alerts)

    def test_warning_revenue_decline_triggers_warning(self):
        mp = _multi_period(rev_change_pct=-12.0)   # -12% < -10%
        alerts = _check_growth(mp)
        rev_alerts = [a for a in alerts if a["metric"] == "revenue_mom_pct"]
        assert any(a["severity"] == "warning" for a in rev_alerts)

    def test_positive_revenue_no_alert(self):
        mp = _multi_period(rev_change_pct=5.0)
        alerts = _check_growth(mp)
        rev_alerts = [a for a in alerts if a["metric"] == "revenue_mom_pct"]
        assert rev_alerts == []

    def test_declining_trend_triggers_warning(self):
        mp = _multi_period(rev_change_pct=2.0, trend="declining")
        alerts = _check_growth(mp)
        trend_alerts = [a for a in alerts if a["metric"] == "net_trend"]
        assert len(trend_alerts) == 1
        assert trend_alerts[0]["severity"] == "warning"

    def test_stable_trend_no_trend_alert(self):
        mp = _multi_period(rev_change_pct=2.0, trend="stable")
        alerts = _check_growth(mp)
        trend_alerts = [a for a in alerts if a["metric"] == "net_trend"]
        assert trend_alerts == []

    def test_returns_list(self):
        assert isinstance(_check_growth({}), list)


# ── _check_budget ─────────────────────────────────────────────────────────────

class TestCheckBudget:

    def test_no_budget_no_alerts(self):
        assert _check_budget(None) == []

    def test_empty_budget_no_alerts(self):
        assert _check_budget({}) == []

    def test_critical_variance_triggers_critical(self):
        budget = _budget(total_var_pct=35.0)  # >30% threshold
        alerts = _check_budget(budget)
        assert any(a["severity"] == "critical" for a in alerts)

    def test_warning_variance_triggers_warning(self):
        budget = _budget(total_var_pct=20.0)  # >15% but <30%
        alerts = _check_budget(budget)
        assert any(a["severity"] == "warning" for a in alerts)

    def test_on_budget_no_alerts(self):
        budget = _budget(total_var_pct=5.0)   # only 5% over
        alerts = _check_budget(budget)
        assert alerts == []

    def test_under_budget_no_alerts(self):
        budget = _budget(total_var_pct=-10.0)  # under budget
        alerts = _check_budget(budget)
        assert alerts == []

    def test_alert_type_is_budget(self):
        budget = _budget(total_var_pct=35.0)
        alerts = _check_budget(budget)
        for a in alerts:
            assert a["type"] == "budget"

    def test_returns_list(self):
        assert isinstance(_check_budget(_budget()), list)


# ── THRESHOLDS sanity ─────────────────────────────────────────────────────────

class TestThresholds:

    def test_critical_thresholds_more_severe_than_warning(self):
        assert THRESHOLDS["gross_margin_critical"] < THRESHOLDS["gross_margin_warning"]
        assert THRESHOLDS["cashflow_runway_critical"] < THRESHOLDS["cashflow_runway_warning"]
        assert THRESHOLDS["budget_variance_warning"] < THRESHOLDS["budget_variance_critical"]

    def test_revenue_decline_thresholds_are_negative(self):
        assert THRESHOLDS["revenue_mom_decline_critical"] < 0
        assert THRESHOLDS["revenue_mom_decline_warning"] < 0

    def test_all_threshold_keys_present(self):
        expected = {
            "gross_margin_critical", "gross_margin_warning",
            "net_margin_critical", "net_margin_warning",
            "cashflow_runway_critical", "cashflow_runway_warning",
            "revenue_mom_decline_critical", "revenue_mom_decline_warning",
            "budget_variance_warning", "budget_variance_critical",
            "tax_payment_days_warning",
        }
        assert expected.issubset(set(THRESHOLDS.keys()))
