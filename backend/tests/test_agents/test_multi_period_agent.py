"""
Tests for multi_period_agent.py — pure computation functions only (no LLM).
Covers: _aggregate_by_month, _pct_change, _compute_mom, _compute_yoy,
        _compute_trend, _compute_kpi_trends
"""
import pytest
from app.agents.multi_period_agent import (
    _aggregate_by_month,
    _pct_change,
    _compute_mom,
    _compute_yoy,
    _compute_trend,
    _compute_kpi_trends,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _tx(date: str, amount: int, tx_type: str = "income", category: str = "revenue") -> dict:
    return {
        "transaction_date": date,
        "amount_cents": amount,
        "type": tx_type,
        "category": category,
    }


def _month(year: int, month: int, revenue: int, expenses: int) -> list[dict]:
    """Generate a single month's transactions."""
    return [
        _tx(f"{year:04d}-{month:02d}-01", revenue, "income", "revenue"),
        _tx(f"{year:04d}-{month:02d}-15", expenses, "expense", "salary"),
    ]


# ── _aggregate_by_month ───────────────────────────────────────────────────────

class TestAggregateByMonth:

    def test_returns_dict(self):
        result = _aggregate_by_month([])
        assert isinstance(result, dict)

    def test_empty_transactions(self):
        result = _aggregate_by_month([])
        assert result == {}

    def test_groups_by_month(self):
        txs = _month(2024, 1, 1_000_000, 600_000) + _month(2024, 2, 1_100_000, 650_000)
        result = _aggregate_by_month(txs)
        assert "2024-01" in result
        assert "2024-02" in result

    def test_revenue_summed_correctly(self):
        txs = [
            _tx("2024-01-05", 500_000, "income", "revenue"),
            _tx("2024-01-20", 600_000, "income", "revenue"),
        ]
        result = _aggregate_by_month(txs)
        assert result["2024-01"]["revenue"] == 1_100_000

    def test_expenses_summed_correctly(self):
        txs = [
            _tx("2024-01-05", 300_000, "expense", "salary"),
            _tx("2024-01-20", 200_000, "expense", "rent"),
        ]
        result = _aggregate_by_month(txs)
        assert result["2024-01"]["expenses"] == 500_000

    def test_net_is_revenue_minus_expenses(self):
        txs = _month(2024, 1, 1_000_000, 700_000)
        result = _aggregate_by_month(txs)
        assert result["2024-01"]["net"] == 300_000

    def test_salary_tracked_separately(self):
        txs = [_tx("2024-01-15", 400_000, "expense", "salary")]
        result = _aggregate_by_month(txs)
        assert result["2024-01"]["salary"] == 400_000

    def test_transaction_without_date_skipped(self):
        txs = [{"amount_cents": 100_000, "type": "income", "category": "revenue"}]
        result = _aggregate_by_month(txs)
        assert result == {}

    def test_different_months_separated(self):
        txs = _month(2024, 1, 1_000_000, 800_000) + _month(2024, 3, 1_200_000, 900_000)
        result = _aggregate_by_month(txs)
        assert "2024-01" in result
        assert "2024-03" in result
        assert "2024-02" not in result  # no February transactions


# ── _pct_change ───────────────────────────────────────────────────────────────

class TestPctChange:

    def test_positive_growth(self):
        assert _pct_change(110, 100) == pytest.approx(10.0)

    def test_negative_growth(self):
        assert _pct_change(90, 100) == pytest.approx(-10.0)

    def test_no_change(self):
        assert _pct_change(100, 100) == pytest.approx(0.0)

    def test_zero_previous_returns_none(self):
        assert _pct_change(100, 0) is None

    def test_large_growth(self):
        assert _pct_change(200, 100) == pytest.approx(100.0)

    def test_result_rounded_to_one_decimal(self):
        result = _pct_change(103, 100)
        assert result == 3.0


# ── _compute_mom ──────────────────────────────────────────────────────────────

class TestComputeMoM:

    def _monthly(self, entries: list[tuple]) -> dict:
        """Build monthly dict from (month_key, revenue, expenses) tuples."""
        return {
            m: {"revenue": r, "expenses": e, "net": r - e, "salary": 0,
                "rent": 0, "utilities": 0, "marketing": 0,
                "technology": 0, "cogs": 0, "other_expense": 0, "tax": 0, "loan": 0}
            for m, r, e in entries
        }

    def test_returns_none_for_single_month(self):
        monthly = self._monthly([("2024-01", 1_000_000, 700_000)])
        assert _compute_mom(monthly) is None

    def test_returns_none_for_empty(self):
        assert _compute_mom({}) is None

    def test_returns_dict_for_two_months(self):
        monthly = self._monthly([
            ("2024-01", 1_000_000, 700_000),
            ("2024-02", 1_100_000, 720_000),
        ])
        result = _compute_mom(monthly)
        assert result is not None

    def test_current_and_previous_month_correct(self):
        monthly = self._monthly([
            ("2024-01", 1_000_000, 700_000),
            ("2024-02", 1_100_000, 720_000),
        ])
        result = _compute_mom(monthly)
        assert result["current_month"] == "2024-02"
        assert result["previous_month"] == "2024-01"

    def test_revenue_change_pct_calculated(self):
        monthly = self._monthly([
            ("2024-01", 1_000_000, 700_000),
            ("2024-02", 1_100_000, 700_000),
        ])
        result = _compute_mom(monthly)
        assert result["revenue_change_pct"] == pytest.approx(10.0)

    def test_required_keys_present(self):
        monthly = self._monthly([
            ("2024-01", 1_000_000, 700_000),
            ("2024-02", 1_100_000, 720_000),
        ])
        result = _compute_mom(monthly)
        for key in ("current_month", "previous_month", "revenue_change_pct",
                    "expenses_change_pct", "net_change_pct",
                    "revenue_current", "revenue_previous",
                    "net_current", "net_previous"):
            assert key in result

    def test_uses_two_most_recent_months(self):
        """With 4 months, MoM should compare month 4 vs month 3."""
        monthly = self._monthly([
            ("2024-01", 500_000, 400_000),
            ("2024-02", 600_000, 450_000),
            ("2024-03", 700_000, 500_000),
            ("2024-04", 800_000, 550_000),
        ])
        result = _compute_mom(monthly)
        assert result["current_month"] == "2024-04"
        assert result["previous_month"] == "2024-03"


# ── _compute_yoy ──────────────────────────────────────────────────────────────

class TestComputeYoY:

    def _monthly(self, entries: list[tuple]) -> dict:
        return {
            m: {"revenue": r, "expenses": e, "net": r - e, "salary": 0,
                "rent": 0, "utilities": 0, "marketing": 0,
                "technology": 0, "cogs": 0, "other_expense": 0, "tax": 0, "loan": 0}
            for m, r, e in entries
        }

    def test_returns_none_without_year_ago_data(self):
        monthly = self._monthly([("2024-01", 1_000_000, 700_000)])
        assert _compute_yoy(monthly) is None

    def test_returns_dict_with_year_ago(self):
        monthly = self._monthly([
            ("2023-06", 800_000, 600_000),
            ("2024-06", 1_000_000, 700_000),
        ])
        result = _compute_yoy(monthly)
        assert result is not None

    def test_yoy_revenue_change_calculated(self):
        monthly = self._monthly([
            ("2023-06", 1_000_000, 700_000),
            ("2024-06", 1_200_000, 700_000),
        ])
        result = _compute_yoy(monthly)
        assert result["revenue_yoy_pct"] == pytest.approx(20.0)

    def test_current_and_year_ago_months(self):
        monthly = self._monthly([
            ("2023-03", 1_000_000, 700_000),
            ("2024-03", 1_100_000, 720_000),
        ])
        result = _compute_yoy(monthly)
        assert result["current_month"] == "2024-03"
        assert result["year_ago_month"] == "2023-03"

    def test_empty_returns_none(self):
        assert _compute_yoy({}) is None


# ── _compute_trend ────────────────────────────────────────────────────────────

class TestComputeTrend:

    def _monthly(self, values: list[tuple]) -> dict:
        return {
            m: {"revenue": r, "expenses": e, "net": r - e, "salary": 0,
                "rent": 0, "utilities": 0, "marketing": 0,
                "technology": 0, "cogs": 0, "other_expense": 0, "tax": 0, "loan": 0}
            for m, r, e in values
        }

    def test_insufficient_data(self):
        monthly = self._monthly([("2024-01", 1_000_000, 700_000)])
        assert _compute_trend(monthly, "net") == "insufficient_data"

    def test_improving_trend(self):
        """Steadily increasing net → improving."""
        monthly = self._monthly([
            ("2024-01", 1_000_000, 900_000),   # net 100k
            ("2024-02", 1_200_000, 900_000),   # net 300k
            ("2024-03", 1_500_000, 900_000),   # net 600k
        ])
        assert _compute_trend(monthly, "net") == "improving"

    def test_declining_trend(self):
        """Steadily decreasing net → declining."""
        monthly = self._monthly([
            ("2024-01", 1_500_000, 900_000),   # net 600k
            ("2024-02", 1_200_000, 900_000),   # net 300k
            ("2024-03", 1_000_000, 900_000),   # net 100k
        ])
        assert _compute_trend(monthly, "net") == "declining"

    def test_stable_trend(self):
        """Flat net → stable."""
        monthly = self._monthly([
            ("2024-01", 1_000_000, 700_000),
            ("2024-02", 1_000_000, 700_000),
            ("2024-03", 1_000_000, 700_000),
        ])
        assert _compute_trend(monthly, "net") == "stable"

    def test_all_zeros_stable(self):
        monthly = {
            "2024-01": {"revenue": 0, "expenses": 0, "net": 0, "salary": 0, "rent": 0,
                        "utilities": 0, "marketing": 0, "technology": 0, "cogs": 0,
                        "other_expense": 0, "tax": 0, "loan": 0},
            "2024-02": {"revenue": 0, "expenses": 0, "net": 0, "salary": 0, "rent": 0,
                        "utilities": 0, "marketing": 0, "technology": 0, "cogs": 0,
                        "other_expense": 0, "tax": 0, "loan": 0},
            "2024-03": {"revenue": 0, "expenses": 0, "net": 0, "salary": 0, "rent": 0,
                        "utilities": 0, "marketing": 0, "technology": 0, "cogs": 0,
                        "other_expense": 0, "tax": 0, "loan": 0},
        }
        result = _compute_trend(monthly, "net")
        assert result in ("stable", "insufficient_data")


# ── _compute_kpi_trends ───────────────────────────────────────────────────────

class TestComputeKPITrends:

    def _monthly(self, entries: list[tuple]) -> dict:
        return {
            m: {"revenue": r, "expenses": e, "net": r - e, "salary": 0,
                "rent": 0, "utilities": 0, "marketing": 0,
                "technology": 0, "cogs": 0, "other_expense": 0, "tax": 0, "loan": 0}
            for m, r, e in entries
        }

    def test_returns_dict_with_three_keys(self):
        monthly = self._monthly([
            ("2024-01", 1_000_000, 700_000),
            ("2024-02", 1_100_000, 710_000),
            ("2024-03", 1_200_000, 720_000),
        ])
        result = _compute_kpi_trends(monthly)
        assert set(result.keys()) == {"revenue_trend", "expense_trend", "net_trend"}

    def test_valid_trend_values(self):
        monthly = self._monthly([
            ("2024-01", 1_000_000, 700_000),
            ("2024-02", 1_100_000, 710_000),
            ("2024-03", 1_200_000, 720_000),
        ])
        result = _compute_kpi_trends(monthly)
        valid = {"improving", "declining", "stable", "insufficient_data"}
        for trend in result.values():
            assert trend in valid

    def test_growing_revenue_improving(self):
        monthly = self._monthly([
            ("2024-01",   500_000, 480_000),
            ("2024-02",   700_000, 480_000),
            ("2024-03", 1_000_000, 480_000),
        ])
        result = _compute_kpi_trends(monthly)
        assert result["revenue_trend"] == "improving"
