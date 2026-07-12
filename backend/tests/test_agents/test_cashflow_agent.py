"""Tests for cash flow agent — pure computation, no LLM calls."""
from app.agents.cashflow_agent import _classify_cashflow, _detect_alerts

SAMPLE_TRANSACTIONS = [
    {"type": "income",  "category": "revenue",  "amount_cents": 500_000, "transaction_date": "2024-01-15"},
    {"type": "expense", "category": "salary",   "amount_cents": 200_000, "transaction_date": "2024-01-20"},
    {"type": "expense", "category": "rent",     "amount_cents":  50_000, "transaction_date": "2024-01-25"},
    {"type": "income",  "category": "revenue",  "amount_cents": 400_000, "transaction_date": "2024-02-10"},
    {"type": "expense", "category": "salary",   "amount_cents": 200_000, "transaction_date": "2024-02-20"},
    {"type": "expense", "category": "loan",     "amount_cents": 100_000, "transaction_date": "2024-02-25"},
]


def test_cashflow_operating():
    cf = _classify_cashflow(SAMPLE_TRANSACTIONS)
    # revenue - salary - rent = (500k + 400k) - (200k + 200k) - 50k = 450k
    assert cf["operating"] == 450_000


def test_cashflow_financing():
    cf = _classify_cashflow(SAMPLE_TRANSACTIONS)
    # loan payment = -100k
    assert cf["financing"] == -100_000


def test_cashflow_net_change():
    cf = _classify_cashflow(SAMPLE_TRANSACTIONS)
    assert cf["net_change"] == cf["operating"] + cf["investing"] + cf["financing"]


def test_cashflow_monthly_series():
    cf = _classify_cashflow(SAMPLE_TRANSACTIONS)
    series = cf["monthly_series"]
    assert len(series) == 2
    assert series[0]["month"] == "2024-01"
    assert series[1]["month"] == "2024-02"


def test_cashflow_empty():
    cf = _classify_cashflow([])
    assert cf["net_change"] == 0
    assert cf["monthly_series"] == []


def test_alerts_negative_operating():
    cf = {"operating": -10_000, "net_change": -10_000, "monthly_series": []}
    alerts = _detect_alerts(cf)
    levels = [a["level"] for a in alerts]
    assert "critical" in levels


def test_alerts_clean():
    cf = {"operating": 100_000, "net_change": 50_000, "monthly_series": []}
    alerts = _detect_alerts(cf)
    assert alerts == []
