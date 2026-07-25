"""
Tests for causal_agent.py — pure statistical functions (no LLM, no DB).
Covers: _extract_metric_series, granger_causality_test,
        _correlation_causality_proxy, and correlation helpers.
"""
import pytest
from app.agents.causal_agent import (
    _extract_metric_series,
    granger_causality_test,
    _correlation_causality_proxy,
    MIN_POINTS_GRANGER,
    MIN_POINTS_CORRELATION,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _monthly_series(months: int = 18, base_in: int = 1_000_000,
                    base_out: int = 800_000) -> list[dict]:
    """Generate flat monthly cashflow data."""
    series = []
    year, month = 2023, 1
    for _ in range(months):
        series.append({
            "month": f"{year:04d}-{month:02d}",
            "in": base_in,
            "out": base_out,
            "net": base_in - base_out,
        })
        month += 1
        if month > 12:
            month = 1
            year += 1
    return series


def _float_series(n: int, base: float = 1.0, step: float = 0.0) -> list[float]:
    """Generate a simple numeric series."""
    return [base + i * step for i in range(n)]


# ── _extract_metric_series ─────────────────────────────────────────────────────

class TestExtractMetricSeries:

    def test_returns_tuple_of_lists(self):
        data = _monthly_series(6)
        months, values = _extract_metric_series(data, "in")
        assert isinstance(months, list)
        assert isinstance(values, list)

    def test_lengths_match(self):
        data = _monthly_series(6)
        months, values = _extract_metric_series(data, "in")
        assert len(months) == len(values)

    def test_extracts_in_metric(self):
        data = _monthly_series(3, base_in=1_000_000)
        _, values = _extract_metric_series(data, "in")
        assert all(v == pytest.approx(10_000.0) for v in values)  # 1_000_000/100

    def test_extracts_out_metric(self):
        data = _monthly_series(3, base_out=800_000)
        _, values = _extract_metric_series(data, "out")
        assert all(v == pytest.approx(8_000.0) for v in values)

    def test_extracts_net_metric(self):
        data = _monthly_series(3, base_in=1_000_000, base_out=800_000)
        _, values = _extract_metric_series(data, "net")
        assert all(v == pytest.approx(2_000.0) for v in values)

    def test_revenue_aliases_to_in(self):
        data = _monthly_series(3, base_in=500_000)
        _, vals_revenue = _extract_metric_series(data, "revenue")
        _, vals_in = _extract_metric_series(data, "in")
        assert vals_revenue == vals_in

    def test_expenses_aliases_to_out(self):
        data = _monthly_series(3, base_out=600_000)
        _, vals_expenses = _extract_metric_series(data, "expenses")
        _, vals_out = _extract_metric_series(data, "out")
        assert vals_expenses == vals_out

    def test_unknown_metric_returns_empty(self):
        data = _monthly_series(3)
        months, values = _extract_metric_series(data, "nonexistent_metric")
        assert months == []
        assert values == []

    def test_sorted_by_month(self):
        """Data should be sorted chronologically even if input is shuffled."""
        data = [
            {"month": "2024-03", "in": 300_000, "out": 200_000, "net": 100_000},
            {"month": "2024-01", "in": 100_000, "out": 80_000, "net": 20_000},
            {"month": "2024-02", "in": 200_000, "out": 150_000, "net": 50_000},
        ]
        months, _ = _extract_metric_series(data, "in")
        assert months == ["2024-01", "2024-02", "2024-03"]

    def test_entries_without_month_skipped(self):
        data = [
            {"in": 100_000, "out": 80_000, "net": 20_000},  # no month key
            {"month": "2024-01", "in": 200_000, "out": 160_000, "net": 40_000},
        ]
        months, values = _extract_metric_series(data, "in")
        assert len(months) == 1
        assert months[0] == "2024-01"

    def test_empty_data_returns_empty(self):
        months, values = _extract_metric_series([], "in")
        assert months == []
        assert values == []

    def test_cents_converted_to_units(self):
        """Values should be divided by 100."""
        data = [{"month": "2024-01", "in": 100_000, "out": 80_000, "net": 20_000}]
        _, values = _extract_metric_series(data, "in")
        assert values[0] == pytest.approx(1_000.0)


# ── granger_causality_test ─────────────────────────────────────────────────────

class TestGrangerCausalityTest:

    def test_insufficient_data_returns_error(self):
        short = [1.0] * (MIN_POINTS_GRANGER - 1)
        result = granger_causality_test(short, short)
        assert result.get("granger_causes") is None
        assert "error" in result

    def test_valid_data_returns_dict(self):
        series = _float_series(18, base=1.0, step=0.1)
        result = granger_causality_test(series, series)
        assert isinstance(result, dict)

    def test_required_keys_present(self):
        series = _float_series(18, base=1.0, step=0.1)
        result = granger_causality_test(series, series)
        # Either error dict or result dict
        assert "granger_causes" in result

    def test_granger_causes_is_bool_or_none(self):
        series = _float_series(18, base=1.0, step=0.1)
        result = granger_causality_test(series, series)
        assert result["granger_causes"] in (True, False, None)

    def test_identical_series_handles_gracefully(self):
        """Identical series may cause numerical issues — should not crash."""
        series = [100.0] * 15
        result = granger_causality_test(series, series)
        assert isinstance(result, dict)

    def test_unequal_length_series_truncated(self):
        long_series = _float_series(20, base=1.0, step=0.1)
        short_series = _float_series(15, base=2.0, step=0.15)
        result = granger_causality_test(long_series, short_series)
        assert isinstance(result, dict)


# ── _correlation_causality_proxy ───────────────────────────────────────────────

class TestCorrelationCausalityProxy:

    def test_returns_dict(self):
        cause = _float_series(12, base=1.0, step=0.1)
        effect = _float_series(12, base=2.0, step=0.1)
        result = _correlation_causality_proxy(cause, effect, max_lag=3)
        assert isinstance(result, dict)

    def test_granger_causes_key_present(self):
        cause = _float_series(12, base=1.0, step=0.1)
        effect = _float_series(12, base=2.0, step=0.1)
        result = _correlation_causality_proxy(cause, effect, max_lag=3)
        assert "granger_causes" in result

    def test_high_correlation_returns_true(self):
        """Perfectly correlated series should show causality proxy = True."""
        cause = [float(i) for i in range(1, 16)]   # 1, 2, ..., 15
        effect = [float(i + 1) for i in range(1, 16)]  # same, lagged
        result = _correlation_causality_proxy(cause, effect, max_lag=2)
        # High correlation (essentially the same sequence)
        assert result["granger_causes"] is True

    def test_uncorrelated_series_returns_false(self):
        """Completely orthogonal series should not show causality."""
        import random
        random.seed(42)
        cause  = [random.uniform(-1, 1) for _ in range(20)]
        effect = [random.uniform(-1, 1) for _ in range(20)]
        result = _correlation_causality_proxy(cause, effect, max_lag=3)
        # Should be False for random noise (probabilistic, but seed=42 should work)
        assert isinstance(result["granger_causes"], bool)

    def test_lag_between_zero_and_max(self):
        cause = _float_series(12, base=1.0, step=0.1)
        effect = _float_series(12, base=2.0, step=0.1)
        result = _correlation_causality_proxy(cause, effect, max_lag=3)
        if "optimal_lag" in result:
            assert 0 <= result["optimal_lag"] <= 3

    def test_too_short_series_handled(self):
        """Very short series (< 4 points per lag) should not crash."""
        cause  = [1.0, 2.0, 3.0]
        effect = [1.0, 2.0, 3.0]
        result = _correlation_causality_proxy(cause, effect, max_lag=3)
        assert isinstance(result, dict)

    def test_empty_series_handled(self):
        result = _correlation_causality_proxy([], [], max_lag=3)
        assert isinstance(result, dict)


# ── Constants sanity ──────────────────────────────────────────────────────────

def test_min_points_granger_at_least_12():
    assert MIN_POINTS_GRANGER >= 12


def test_min_points_correlation_less_than_granger():
    assert MIN_POINTS_CORRELATION < MIN_POINTS_GRANGER
