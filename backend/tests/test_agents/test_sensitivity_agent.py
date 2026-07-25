"""
Tests for sensitivity_agent.py — pure computation functions (no LLM, no DB).
Covers: _apply_variable, compute_sensitivity_matrix
"""
import pytest
from app.agents.sensitivity_agent import (
    _apply_variable,
    compute_sensitivity_matrix,
    DEFAULT_RANGES,
    VARIABLE_LABELS,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

BASE_PNL = {
    "revenue":     2_000_000,
    "cogs":          600_000,
    "gross_profit": 1_400_000,
    "total_opex":    800_000,
    "ebitda":        600_000,
    "net_income":    500_000,
    "tax":            50_000,
    "loan_payments":  50_000,
    "gross_margin":  0.70,
    "ebitda_margin": 0.30,
    "net_margin":    0.25,
    "opex": {
        "salary":    500_000,
        "rent":      150_000,
        "marketing": 150_000,
    },
}


# ── _apply_variable ───────────────────────────────────────────────────────────

class TestApplyVariable:

    def test_does_not_mutate_original(self):
        original_revenue = BASE_PNL["revenue"]
        _apply_variable(BASE_PNL, "pricing_change_pct", 10)
        assert BASE_PNL["revenue"] == original_revenue

    def test_pricing_increase_raises_revenue(self):
        result = _apply_variable(BASE_PNL, "pricing_change_pct", 10)
        assert result["revenue"] > BASE_PNL["revenue"]

    def test_pricing_decrease_lowers_revenue(self):
        result = _apply_variable(BASE_PNL, "pricing_change_pct", -10)
        assert result["revenue"] < BASE_PNL["revenue"]

    def test_pricing_zero_change_no_revenue_change(self):
        result = _apply_variable(BASE_PNL, "pricing_change_pct", 0)
        assert result["revenue"] == BASE_PNL["revenue"]

    def test_headcount_increase_raises_salary(self):
        result = _apply_variable(BASE_PNL, "headcount_change_pct", 20)
        assert result["opex"]["salary"] > BASE_PNL["opex"]["salary"]

    def test_headcount_decrease_lowers_salary(self):
        result = _apply_variable(BASE_PNL, "headcount_change_pct", -20)
        assert result["opex"]["salary"] < BASE_PNL["opex"]["salary"]

    def test_headcount_change_updates_total_opex(self):
        result_up = _apply_variable(BASE_PNL, "headcount_change_pct", 20)
        result_dn = _apply_variable(BASE_PNL, "headcount_change_pct", -20)
        assert result_up["total_opex"] > BASE_PNL["total_opex"]
        assert result_dn["total_opex"] < BASE_PNL["total_opex"]

    def test_cogs_increase_raises_cogs(self):
        result = _apply_variable(BASE_PNL, "cogs_change_pct", 15)
        assert result["cogs"] > BASE_PNL["cogs"]

    def test_cogs_increase_lowers_gross_profit(self):
        result = _apply_variable(BASE_PNL, "cogs_change_pct", 15)
        assert result["gross_profit"] < BASE_PNL["gross_profit"]

    def test_opex_increase_lowers_ebitda(self):
        result = _apply_variable(BASE_PNL, "opex_change_pct", 20)
        assert result["ebitda"] < BASE_PNL["ebitda"]

    def test_opex_decrease_raises_ebitda(self):
        result = _apply_variable(BASE_PNL, "opex_change_pct", -20)
        assert result["ebitda"] > BASE_PNL["ebitda"]

    def test_growth_rate_change_affects_revenue(self):
        result_up = _apply_variable(BASE_PNL, "growth_rate_change_pct", 10)
        result_dn = _apply_variable(BASE_PNL, "growth_rate_change_pct", -10)
        assert result_up["revenue"] > BASE_PNL["revenue"]
        assert result_dn["revenue"] < BASE_PNL["revenue"]

    def test_net_income_recomputed_after_change(self):
        result = _apply_variable(BASE_PNL, "pricing_change_pct", 20)
        expected = result["ebitda"] - result.get("tax", 0) - result.get("loan_payments", 0)
        assert result["net_income"] == expected

    def test_gross_margin_recomputed(self):
        result = _apply_variable(BASE_PNL, "pricing_change_pct", 10)
        expected = round(result["gross_profit"] / result["revenue"], 4)
        assert result["gross_margin"] == pytest.approx(expected)

    def test_zero_revenue_does_not_crash(self):
        pnl = dict(BASE_PNL)
        pnl["revenue"] = 0
        # Should not raise ZeroDivisionError
        result = _apply_variable(pnl, "pricing_change_pct", 10)
        assert isinstance(result, dict)

    def test_unknown_variable_returns_pnl_unchanged_metrics(self):
        """Unknown variable should still recompute gross_profit etc."""
        result = _apply_variable(BASE_PNL, "unknown_variable", 10)
        # gross_profit = revenue - cogs (unchanged since unknown var)
        assert result["gross_profit"] == BASE_PNL["revenue"] - BASE_PNL["cogs"]


# ── compute_sensitivity_matrix ────────────────────────────────────────────────

class TestComputeSensitivityMatrix:

    def _run(self, row_var="pricing_change_pct", col_var="opex_change_pct",
             row_range=None, col_range=None):
        return compute_sensitivity_matrix(
            BASE_PNL, row_var, col_var,
            row_range=row_range or [-10, 0, 10],
            col_range=col_range or [-10, 0, 10],
        )

    def test_required_keys_present(self):
        result = self._run()
        for key in ("row_variable", "col_variable", "row_values", "col_values",
                    "matrix", "matrix_margin", "base_net_income",
                    "best_case", "worst_case"):
            assert key in result

    def test_matrix_dimensions_correct(self):
        result = compute_sensitivity_matrix(
            BASE_PNL, "pricing_change_pct", "opex_change_pct",
            row_range=[-10, 0, 10],
            col_range=[-5, 0, 5, 10],
        )
        assert len(result["matrix"]) == 3        # 3 row values
        assert len(result["matrix"][0]) == 4     # 4 col values

    def test_matrix_margin_same_dimensions(self):
        result = self._run()
        assert len(result["matrix_margin"]) == len(result["matrix"])
        for r_net, r_margin in zip(result["matrix"], result["matrix_margin"]):
            assert len(r_net) == len(r_margin)

    def test_base_net_income_matches_pnl(self):
        result = self._run()
        assert result["base_net_income"] == BASE_PNL["net_income"]

    def test_best_case_net_income_highest(self):
        result = self._run()
        all_vals = [v for row in result["matrix"] for v in row]
        assert result["best_case"]["net_income"] == max(all_vals)

    def test_worst_case_net_income_lowest(self):
        result = self._run()
        all_vals = [v for row in result["matrix"] for v in row]
        assert result["worst_case"]["net_income"] == min(all_vals)

    def test_best_gt_worst(self):
        result = self._run()
        assert result["best_case"]["net_income"] >= result["worst_case"]["net_income"]

    def test_row_variable_name_stored(self):
        result = self._run(row_var="pricing_change_pct")
        assert result["row_variable"] == "pricing_change_pct"

    def test_col_variable_name_stored(self):
        result = self._run(col_var="opex_change_pct")
        assert result["col_variable"] == "opex_change_pct"

    def test_labels_populated(self):
        result = self._run()
        assert result["row_label"]  # not empty
        assert result["col_label"]

    def test_default_ranges_used_when_none(self):
        """When row_range/col_range are None, DEFAULT_RANGES should be used."""
        result = compute_sensitivity_matrix(
            BASE_PNL, "pricing_change_pct", "opex_change_pct",
        )
        expected_row = DEFAULT_RANGES["pricing_change_pct"]
        assert result["row_values"] == expected_row

    def test_zero_change_row_produces_pnl_net_income(self):
        """Row at 0% and Col at 0% should equal base net income."""
        result = compute_sensitivity_matrix(
            BASE_PNL, "pricing_change_pct", "opex_change_pct",
            row_range=[0], col_range=[0],
        )
        assert result["matrix"][0][0] == BASE_PNL["net_income"]

    def test_higher_pricing_improves_net_income_same_opex(self):
        """With opex fixed at 0%, higher pricing should give better net income."""
        result = compute_sensitivity_matrix(
            BASE_PNL, "pricing_change_pct", "opex_change_pct",
            row_range=[-10, 0, 10], col_range=[0],
        )
        net_low  = result["matrix"][0][0]  # -10% pricing
        net_base = result["matrix"][1][0]  #   0% pricing
        net_high = result["matrix"][2][0]  # +10% pricing
        assert net_low < net_base < net_high

    def test_higher_opex_lowers_net_income_same_pricing(self):
        """With pricing fixed, higher opex should lower net income."""
        result = compute_sensitivity_matrix(
            BASE_PNL, "pricing_change_pct", "opex_change_pct",
            row_range=[0], col_range=[-10, 0, 10],
        )
        net_low  = result["matrix"][0][0]  # opex -10%
        net_base = result["matrix"][0][1]  # opex   0%
        net_high = result["matrix"][0][2]  # opex +10%
        assert net_high < net_base < net_low


# ── DEFAULT_RANGES sanity ─────────────────────────────────────────────────────

class TestDefaultRanges:

    def test_all_variables_have_ranges(self):
        for var in ("headcount_change_pct", "pricing_change_pct",
                    "growth_rate_change_pct", "cogs_change_pct", "opex_change_pct"):
            assert var in DEFAULT_RANGES
            assert len(DEFAULT_RANGES[var]) >= 3

    def test_zero_always_in_ranges(self):
        for var, rng in DEFAULT_RANGES.items():
            assert 0 in rng or 0.0 in rng, f"0 not in range for {var}"

    def test_all_variables_have_labels(self):
        for var in DEFAULT_RANGES:
            assert var in VARIABLE_LABELS
            assert VARIABLE_LABELS[var]  # non-empty
