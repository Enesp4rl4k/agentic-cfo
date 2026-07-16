"""
Tests for P&L agent — pure computation, no LLM calls.
done_when: pytest tests/test_agents/test_pnl_agent.py -q → pass
"""
from app.agents.pnl_agent import _compute_pnl


SAMPLE_TRANSACTIONS = [
    {"type": "income",  "category": "revenue",    "amount_cents": 500_000},  # $5,000
    {"type": "income",  "category": "revenue",    "amount_cents": 300_000},  # $3,000
    {"type": "expense", "category": "cogs",       "amount_cents": 200_000},  # $2,000
    {"type": "expense", "category": "salary",     "amount_cents": 150_000},  # $1,500
    {"type": "expense", "category": "rent",       "amount_cents":  50_000},  # $500
    {"type": "expense", "category": "utilities",  "amount_cents":  20_000},  # $200
    {"type": "expense", "category": "tax",        "amount_cents":  80_000},  # $800
]


def test_pnl_revenue():
    pnl = _compute_pnl(SAMPLE_TRANSACTIONS)
    assert pnl["revenue"] == 800_000


def test_pnl_cogs():
    pnl = _compute_pnl(SAMPLE_TRANSACTIONS)
    assert pnl["cogs"] == 200_000


def test_pnl_gross_profit():
    pnl = _compute_pnl(SAMPLE_TRANSACTIONS)
    assert pnl["gross_profit"] == 600_000


def test_pnl_gross_margin():
    pnl = _compute_pnl(SAMPLE_TRANSACTIONS)
    assert abs(pnl["gross_margin"] - 0.75) < 0.001


def test_pnl_net_income():
    pnl = _compute_pnl(SAMPLE_TRANSACTIONS)
    # gross_profit - opex - tax = 600k - 220k - 80k = 300k
    assert pnl["net_income"] == 300_000


def test_pnl_net_margin():
    pnl = _compute_pnl(SAMPLE_TRANSACTIONS)
    assert abs(pnl["net_margin"] - 0.375) < 0.001


def test_pnl_empty_transactions():
    pnl = _compute_pnl([])
    assert pnl["revenue"] == 0
    assert pnl["net_income"] == 0
    assert pnl["gross_margin"] == 0.0


def test_pnl_opex_breakdown():
    pnl = _compute_pnl(SAMPLE_TRANSACTIONS)
    assert pnl["opex"]["salary"] == 150_000
    assert pnl["opex"]["rent"] == 50_000
    assert pnl["opex"]["utilities"] == 20_000
