"""The persisted dashboard is read one way (plan v6 §S0/§S4)."""
from app.services.dashboard_contract import period_opex, revenue


def test_period_opex_sums_the_dashboard_categories():
    assert period_opex({"opex": {"salary": 300.0, "rent": 120.5}}) == 420.5


def test_period_opex_accepts_the_pnl_agent_total():
    assert period_opex({"total_opex": 999.0, "opex": {"salary": 1.0}}) == 999.0


def test_period_opex_is_unknown_not_zero():
    assert period_opex(None) is None
    assert period_opex({}) is None
    assert period_opex({"opex": {}}) is None
    assert period_opex({"opex": {"salary": 10.0, "rent": "n/a"}}) is None


def test_revenue_ignores_non_numbers():
    assert revenue({"revenue": 1_000.0}) == 1_000.0
    assert revenue({"revenue": True}) is None
    assert revenue(None) is None
