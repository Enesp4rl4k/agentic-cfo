"""
Tests for forecast_agent.py — pure computation functions only (no LLM).
Covers: _detect_seasonality, _extrapolate, _compute_scenarios.

forecast_agent.py imports langchain_openai at module level, so we mock it
before the import to keep tests self-contained and dependency-free.
"""
import sys
import types
import pytest

# ── Stub out heavy LangChain dependencies before importing the agent ──────────
for _mod in (
    "langchain_openai",
    "langchain_core",
    "langchain_core.messages",
):
    if _mod not in sys.modules:
        sys.modules[_mod] = types.ModuleType(_mod)

# Provide stub classes expected at top level of langchain_openai
_lc_openai = sys.modules["langchain_openai"]
if not hasattr(_lc_openai, "ChatOpenAI"):
    _lc_openai.ChatOpenAI = object  # type: ignore[attr-defined]

_lc_core_msgs = sys.modules["langchain_core.messages"]
for _cls in ("HumanMessage", "SystemMessage", "AIMessage"):
    if not hasattr(_lc_core_msgs, _cls):
        setattr(_lc_core_msgs, _cls, object)

from app.agents.forecast_agent import (  # noqa: E402
    _detect_seasonality,
    _extrapolate,
    _compute_scenarios,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_series(months: int, base_in: int = 1_000_000, base_out: int = 800_000) -> list[dict]:
    """Generate a flat monthly series starting 2023-01."""
    series = []
    year, month = 2023, 1
    for i in range(months):
        series.append({"month": f"{year:04d}-{month:02d}", "in": base_in, "out": base_out, "net": base_in - base_out})
        month += 1
        if month > 12:
            month = 1
            year += 1
    return series


def _make_growing_series(months: int, start_in: int = 500_000, growth: float = 1.05) -> list[dict]:
    """Series with steady income growth."""
    series = []
    year, month = 2023, 1
    cur = start_in
    for i in range(months):
        out = int(cur * 0.8)
        series.append({"month": f"{year:04d}-{month:02d}", "in": cur, "out": out, "net": cur - out})
        cur = int(cur * growth)
        month += 1
        if month > 12:
            month = 1
            year += 1
    return series


# ── _detect_seasonality ───────────────────────────────────────────────────────

class TestDetectSeasonality:

    def test_returns_empty_for_short_series(self):
        series = _make_series(6)
        result = _detect_seasonality(series)
        assert result == {}

    def test_returns_empty_for_empty_series(self):
        assert _detect_seasonality([]) == {}

    def test_returns_dict_for_12_months(self):
        series = _make_series(12)
        result = _detect_seasonality(series)
        assert isinstance(result, dict)

    def test_keys_are_month_numbers(self):
        series = _make_series(12)
        result = _detect_seasonality(series)
        if result:
            for k in result:
                assert 1 <= k <= 12

    def test_uniform_series_indices_near_one(self):
        """Flat series should produce seasonality indices close to 1.0."""
        series = _make_series(24, base_in=1_000_000)
        result = _detect_seasonality(series)
        for idx in result.values():
            assert abs(idx - 1.0) < 0.05

    def test_returns_empty_when_all_values_zero(self):
        series = [{"month": f"2023-{m:02d}", "in": 0, "out": 0, "net": 0} for m in range(1, 13)]
        result = _detect_seasonality(series)
        # global_mean == 0 → should return {}
        assert result == {}


# ── _extrapolate ──────────────────────────────────────────────────────────────

class TestExtrapolate:

    def test_returns_correct_number_of_months(self):
        series = _make_series(6)
        result = _extrapolate(series, 12, 1.02)
        assert len(result) == 12

    def test_returns_empty_for_empty_series(self):
        result = _extrapolate([], 12, 1.02)
        assert result == []

    def test_projected_flag_is_true(self):
        series = _make_series(3)
        result = _extrapolate(series, 3, 1.0)
        for entry in result:
            assert entry["projected"] is True

    def test_required_keys_present(self):
        series = _make_series(3)
        result = _extrapolate(series, 3, 1.0)
        for entry in result:
            for key in ("month", "in", "out", "net"):
                assert key in entry

    def test_months_are_sequential(self):
        """Projected months should follow on from the last historical month."""
        series = _make_series(3)   # ends at 2023-03
        result = _extrapolate(series, 3, 1.0)
        assert result[0]["month"] == "2023-04"
        assert result[1]["month"] == "2023-05"
        assert result[2]["month"] == "2023-06"

    def test_year_wraps_correctly(self):
        """Series ending in December should wrap to January next year."""
        series = [{"month": "2023-12", "in": 1_000_000, "out": 800_000, "net": 200_000}]
        result = _extrapolate(series, 2, 1.0)
        assert result[0]["month"] == "2024-01"
        assert result[1]["month"] == "2024-02"

    def test_growth_rate_above_one_increases_income(self):
        series = _make_series(3, base_in=1_000_000)
        result = _extrapolate(series, 3, 1.05)
        # Income should increase over time with 1.05 growth
        assert result[2]["in"] > result[0]["in"]

    def test_growth_rate_below_one_decreases_income(self):
        series = _make_series(3, base_in=1_000_000)
        result = _extrapolate(series, 3, 0.95)
        # Income should decrease over time with 0.95 growth
        assert result[2]["in"] < result[0]["in"]

    def test_net_equals_in_minus_out(self):
        series = _make_series(3)
        result = _extrapolate(series, 6, 1.02)
        for entry in result:
            assert entry["net"] == entry["in"] - entry["out"]

    def test_seasonality_indices_applied(self):
        """With a doubled December index, December in should be ~2x normal."""
        series = _make_series(12)   # ends at 2023-12
        # Override December (month 12) with index 2.0
        indices = {m: 1.0 for m in range(1, 13)}
        indices[1] = 2.0  # next month after Dec is Jan
        result = _extrapolate(series, 1, 1.0, seasonality_indices=indices)
        assert result[0]["seasonal_index"] == pytest.approx(2.0)

    def test_no_seasonality_index_is_none(self):
        series = _make_series(3)
        result = _extrapolate(series, 1, 1.0, seasonality_indices=None)
        assert result[0]["seasonal_index"] is None

    def test_uses_last_three_months_as_baseline(self):
        """Baseline average should come from the last 3 months, not earlier ones."""
        # First months have low income, last 3 are high
        series = _make_series(3, base_in=100_000) + _make_series(3, base_in=900_000)
        # Manually fix months
        for i, entry in enumerate(series):
            year = 2023
            month = i + 1
            if month > 12:
                month -= 12
                year += 1
            entry["month"] = f"{year:04d}-{month:02d}"
        result = _extrapolate(series, 1, 1.0)
        # Baseline should be ~900_000, not the average of all 6
        assert result[0]["in"] > 500_000


# ── _compute_scenarios ────────────────────────────────────────────────────────

class TestComputeScenarios:

    def _cashflow(self, months: int = 6) -> dict:
        return {"monthly_series": _make_series(months, 1_000_000, 800_000)}

    def test_returns_three_scenarios(self):
        result = _compute_scenarios(self._cashflow(), {})
        assert set(result.keys()) == {"optimistic", "base", "pessimistic"}

    def test_each_scenario_has_required_keys(self):
        result = _compute_scenarios(self._cashflow(), {})
        for scenario in result.values():
            for key in ("label", "description", "growth_rate", "months",
                        "runway_months", "twelve_month_net"):
                assert key in scenario

    def test_each_scenario_has_12_months(self):
        result = _compute_scenarios(self._cashflow(), {})
        for scenario in result.values():
            assert len(scenario["months"]) == 12

    def test_optimistic_net_greater_than_pessimistic(self):
        result = _compute_scenarios(self._cashflow(), {})
        opt_net = result["optimistic"]["twelve_month_net"]
        pess_net = result["pessimistic"]["twelve_month_net"]
        assert opt_net > pess_net

    def test_base_net_between_optimistic_and_pessimistic(self):
        result = _compute_scenarios(self._cashflow(), {})
        opt_net  = result["optimistic"]["twelve_month_net"]
        base_net = result["base"]["twelve_month_net"]
        pess_net = result["pessimistic"]["twelve_month_net"]
        assert pess_net <= base_net <= opt_net

    def test_runway_months_none_when_always_positive(self):
        """High income relative to expenses — runway should be None (stable)."""
        cf = {"monthly_series": _make_series(6, base_in=2_000_000, base_out=500_000)}
        result = _compute_scenarios(cf, {})
        assert result["optimistic"]["runway_months"] is None

    def test_runway_months_set_when_deficit(self):
        """Low income vs high expenses — pessimistic scenario should hit runway."""
        cf = {"monthly_series": _make_series(6, base_in=500_000, base_out=900_000)}
        result = _compute_scenarios(cf, {})
        assert result["pessimistic"]["runway_months"] is not None
        assert result["pessimistic"]["runway_months"] <= 12

    def test_empty_series_returns_empty_months(self):
        result = _compute_scenarios({"monthly_series": []}, {})
        for scenario in result.values():
            assert scenario["months"] == []

    def test_growth_rates_are_correct(self):
        result = _compute_scenarios(self._cashflow(), {})
        assert result["optimistic"]["growth_rate"]  == pytest.approx(1.05)
        assert result["base"]["growth_rate"]        == pytest.approx(1.01)
        assert result["pessimistic"]["growth_rate"] == pytest.approx(0.97)

    def test_twelve_month_net_matches_sum_of_months(self):
        result = _compute_scenarios(self._cashflow(), {})
        for scenario in result.values():
            expected_sum = sum(m["net"] for m in scenario["months"])
            assert scenario["twelve_month_net"] == expected_sum

    def test_seasonality_applied_flag_false_for_short_series(self):
        """< 12 months of history → no seasonality."""
        result = _compute_scenarios(self._cashflow(6), {})
        for scenario in result.values():
            assert scenario["seasonality_applied"] is False

    def test_seasonality_applied_flag_true_for_long_series(self):
        """≥ 12 months of history → seasonality detection runs."""
        result = _compute_scenarios(self._cashflow(24), {})
        for scenario in result.values():
            assert scenario["seasonality_applied"] is True
