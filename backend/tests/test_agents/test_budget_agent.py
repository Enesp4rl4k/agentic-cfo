"""
Tests for budget_agent.py — pure computation functions only (no LLM).
"""
import pytest
from app.agents.budget_agent import _compute_budget_variance


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _tx(category: str, amount: int, tx_type: str = "expense") -> dict:
    return {"category": category, "amount_cents": amount, "type": tx_type}


BUDGET_INPUT = {
    "period": "2024-01",
    "items": [
        {"category": "salary",    "budgeted": 500_000},
        {"category": "rent",      "budgeted": 150_000},
        {"category": "marketing", "budgeted": 100_000},
    ],
}

TRANSACTIONS = [
    _tx("salary",    550_000),   # over budget by 50k
    _tx("rent",      150_000),   # on target
    _tx("marketing",  80_000),   # under budget by 20k
    _tx("revenue", 1_000_000, "income"),  # income — should be ignored
]


# ── Basic structure ────────────────────────────────────────────────────────────

class TestComputeBudgetVariance:

    def test_returns_dict(self):
        result = _compute_budget_variance(TRANSACTIONS, BUDGET_INPUT)
        assert isinstance(result, dict)

    def test_items_count_matches_budget_input(self):
        result = _compute_budget_variance(TRANSACTIONS, BUDGET_INPUT)
        assert len(result["items"]) == 3

    def test_required_keys_present(self):
        result = _compute_budget_variance(TRANSACTIONS, BUDGET_INPUT)
        for key in ("items", "total_budgeted", "total_actual",
                    "total_variance", "total_variance_pct",
                    "over_budget_categories", "period"):
            assert key in result

    def test_period_propagated(self):
        result = _compute_budget_variance(TRANSACTIONS, BUDGET_INPUT)
        assert result["period"] == "2024-01"


# ── Per-item variance ──────────────────────────────────────────────────────────

class TestItemVariance:

    def setup_method(self):
        result = _compute_budget_variance(TRANSACTIONS, BUDGET_INPUT)
        self.items = {i["category"]: i for i in result["items"]}

    def test_salary_over_budget(self):
        item = self.items["salary"]
        assert item["variance"] == 50_000          # 550k - 500k
        assert item["status"] == "over"

    def test_rent_on_target(self):
        item = self.items["rent"]
        assert item["variance"] == 0
        assert item["status"] == "on_target"

    def test_marketing_under_budget(self):
        item = self.items["marketing"]
        assert item["variance"] == -20_000         # 80k - 100k
        assert item["status"] == "under"

    def test_variance_pct_salary(self):
        item = self.items["salary"]
        # 50_000 / 500_000 * 100 = 10.0
        assert item["variance_pct"] == pytest.approx(10.0)

    def test_variance_pct_marketing(self):
        item = self.items["marketing"]
        # -20_000 / 100_000 * 100 = -20.0
        assert item["variance_pct"] == pytest.approx(-20.0)

    def test_income_transactions_ignored(self):
        # Revenue transaction should not appear in expense actuals
        assert "revenue" not in self.items


# ── Totals ────────────────────────────────────────────────────────────────────

class TestBudgetTotals:

    def setup_method(self):
        self.result = _compute_budget_variance(TRANSACTIONS, BUDGET_INPUT)

    def test_total_budgeted(self):
        assert self.result["total_budgeted"] == 750_000  # 500k+150k+100k

    def test_total_actual(self):
        assert self.result["total_actual"] == 780_000    # 550k+150k+80k

    def test_total_variance(self):
        assert self.result["total_variance"] == 30_000   # 780k-750k

    def test_total_variance_pct(self):
        # 30_000 / 750_000 * 100 = 4.0
        assert self.result["total_variance_pct"] == pytest.approx(4.0)

    def test_over_budget_categories(self):
        assert "salary" in self.result["over_budget_categories"]
        assert "rent" not in self.result["over_budget_categories"]
        assert "marketing" not in self.result["over_budget_categories"]


# ── Sorting ───────────────────────────────────────────────────────────────────

def test_items_sorted_most_over_first():
    """Items should be sorted by variance descending (worst offender first)."""
    result = _compute_budget_variance(TRANSACTIONS, BUDGET_INPUT)
    variances = [i["variance"] for i in result["items"]]
    assert variances == sorted(variances, reverse=True)


# ── Edge cases ────────────────────────────────────────────────────────────────

def test_empty_budget_items_returns_empty_dict():
    result = _compute_budget_variance(TRANSACTIONS, {"items": []})
    assert result == {}


def test_empty_transactions_all_under_budget():
    result = _compute_budget_variance([], BUDGET_INPUT)
    for item in result["items"]:
        assert item["actual"] == 0
        assert item["status"] == "under"


def test_no_matching_category_actual_is_zero():
    budget = {"items": [{"category": "utilities", "budgeted": 50_000}]}
    result = _compute_budget_variance(TRANSACTIONS, budget)
    assert result["items"][0]["actual"] == 0


def test_zero_budgeted_variance_pct_is_zero():
    budget = {"items": [{"category": "salary", "budgeted": 0}]}
    txs = [_tx("salary", 100_000)]
    result = _compute_budget_variance(txs, budget)
    # Division by zero should be handled gracefully
    assert result["items"][0]["variance_pct"] == 0.0


def test_single_category_exactly_on_budget():
    budget = {"items": [{"category": "rent", "budgeted": 100_000}]}
    txs = [_tx("rent", 100_000)]
    result = _compute_budget_variance(txs, budget)
    item = result["items"][0]
    assert item["variance"] == 0
    assert item["status"] == "on_target"
    assert item["variance_pct"] == 0.0


def test_multiple_transactions_same_category_are_summed():
    budget = {"items": [{"category": "marketing", "budgeted": 200_000}]}
    txs = [
        _tx("marketing", 80_000),
        _tx("marketing", 60_000),
        _tx("marketing", 40_000),
    ]
    result = _compute_budget_variance(txs, budget)
    assert result["items"][0]["actual"] == 180_000


def test_over_budget_categories_list_correct():
    budget = {
        "items": [
            {"category": "salary",    "budgeted": 100_000},
            {"category": "marketing", "budgeted": 200_000},
            {"category": "rent",      "budgeted": 50_000},
        ]
    }
    txs = [
        _tx("salary",    150_000),  # over
        _tx("marketing", 180_000),  # under
        _tx("rent",       50_000),  # on target
    ]
    result = _compute_budget_variance(txs, budget)
    assert result["over_budget_categories"] == ["salary"]
