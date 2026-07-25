"""
Tests for tax_agent.py — pure computation functions only (no LLM).
Covers Turkish tax calculations: VAT (KDV), withholding (stopaj),
corporate tax (kurumlar vergisi), and payment calendar.
"""
import pytest
from app.agents.tax_agent import (
    _compute_vat,
    _compute_withholding,
    _compute_corporate_tax,
    _build_payment_calendar,
    VAT_RATE,
    WITHHOLDING_RATE,
    CORPORATE_TAX_RATE,
    SSI_RATE,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _tx(category: str, amount: int, tx_type: str = "expense") -> dict:
    return {"category": category, "amount_cents": amount, "type": tx_type}


# ── VAT (KDV) Tests ───────────────────────────────────────────────────────────

class TestComputeVAT:

    def test_output_vat_from_revenue(self):
        txs = [_tx("revenue", 1_000_000, "income")]
        result = _compute_vat(txs)
        assert result["output_vat"] == int(1_000_000 * VAT_RATE)

    def test_output_vat_from_other_income(self):
        txs = [_tx("other_income", 500_000, "income")]
        result = _compute_vat(txs)
        assert result["output_vat"] == int(500_000 * VAT_RATE)

    def test_input_vat_from_cogs(self):
        txs = [_tx("cogs", 400_000)]
        result = _compute_vat(txs)
        assert result["input_vat"] == int(400_000 * VAT_RATE)

    def test_input_vat_from_technology(self):
        txs = [_tx("technology", 200_000)]
        result = _compute_vat(txs)
        assert result["input_vat"] == int(200_000 * VAT_RATE)

    def test_input_vat_from_marketing(self):
        txs = [_tx("marketing", 300_000)]
        result = _compute_vat(txs)
        assert result["input_vat"] == int(300_000 * VAT_RATE)

    def test_input_vat_from_rent(self):
        txs = [_tx("rent", 150_000)]
        result = _compute_vat(txs)
        assert result["input_vat"] == int(150_000 * VAT_RATE)

    def test_net_vat_payable_positive(self):
        txs = [
            _tx("revenue", 1_000_000, "income"),
            _tx("cogs",    400_000),
        ]
        result = _compute_vat(txs)
        expected = int(1_000_000 * VAT_RATE) - int(400_000 * VAT_RATE)
        assert result["net_vat_payable"] == expected

    def test_net_vat_not_negative(self):
        """When input VAT > output VAT, net payable should be 0 (not negative)."""
        txs = [
            _tx("revenue",    100_000, "income"),
            _tx("technology", 900_000),
        ]
        result = _compute_vat(txs)
        assert result["net_vat_payable"] == 0

    def test_salary_not_subject_to_vat(self):
        """Salary expenses do not generate input VAT."""
        txs = [_tx("salary", 500_000)]
        result = _compute_vat(txs)
        assert result["input_vat"] == 0

    def test_empty_transactions(self):
        result = _compute_vat([])
        assert result == {"output_vat": 0, "input_vat": 0, "net_vat_payable": 0}

    def test_required_keys_present(self):
        result = _compute_vat([])
        for key in ("output_vat", "input_vat", "net_vat_payable"):
            assert key in result


# ── Withholding (Stopaj) Tests ─────────────────────────────────────────────────

class TestComputeWithholding:

    def test_withholding_from_salary(self):
        txs = [_tx("salary", 1_000_000)]
        result = _compute_withholding(txs)
        assert result["income_tax_withholding"] == int(1_000_000 * WITHHOLDING_RATE)

    def test_ssi_from_salary(self):
        txs = [_tx("salary", 1_000_000)]
        result = _compute_withholding(txs)
        assert result["ssi_employer"] == int(1_000_000 * SSI_RATE)

    def test_total_payroll_tax_is_sum(self):
        txs = [_tx("salary", 1_000_000)]
        result = _compute_withholding(txs)
        assert result["total_payroll_tax"] == (
            result["income_tax_withholding"] + result["ssi_employer"]
        )

    def test_salary_base_equals_total_salary(self):
        txs = [
            _tx("salary", 600_000),
            _tx("salary", 400_000),
        ]
        result = _compute_withholding(txs)
        assert result["salary_base"] == 1_000_000

    def test_non_salary_categories_excluded(self):
        txs = [_tx("rent", 500_000), _tx("marketing", 200_000)]
        result = _compute_withholding(txs)
        assert result["salary_base"] == 0
        assert result["income_tax_withholding"] == 0
        assert result["ssi_employer"] == 0

    def test_income_transactions_excluded(self):
        txs = [_tx("salary", 500_000, "income")]  # type=income, not expense
        result = _compute_withholding(txs)
        assert result["salary_base"] == 0

    def test_empty_transactions(self):
        result = _compute_withholding([])
        assert result["salary_base"] == 0
        assert result["total_payroll_tax"] == 0

    def test_required_keys_present(self):
        result = _compute_withholding([])
        for key in ("salary_base", "income_tax_withholding",
                    "ssi_employer", "total_payroll_tax"):
            assert key in result


# ── Corporate Tax Tests ────────────────────────────────────────────────────────

class TestComputeCorporateTax:

    def test_positive_ebitda_generates_tax(self):
        pnl = {"ebitda": 1_000_000}
        result = _compute_corporate_tax(pnl)
        assert result["corporate_tax_estimate"] > 0

    def test_tax_calculation_with_depreciation(self):
        pnl = {"ebitda": 1_000_000}
        result = _compute_corporate_tax(pnl)
        # taxable = 1_000_000 - int(1_000_000 * 0.05) = 950_000
        expected_taxable = 1_000_000 - int(1_000_000 * 0.05)
        assert result["taxable_income"] == expected_taxable
        assert result["corporate_tax_estimate"] == int(expected_taxable * CORPORATE_TAX_RATE)

    def test_zero_ebitda_no_tax(self):
        pnl = {"ebitda": 0}
        result = _compute_corporate_tax(pnl)
        assert result["corporate_tax_estimate"] == 0
        assert result["taxable_income"] == 0

    def test_negative_ebitda_no_tax(self):
        pnl = {"ebitda": -500_000}
        result = _compute_corporate_tax(pnl)
        assert result["corporate_tax_estimate"] == 0

    def test_missing_ebitda_treated_as_zero(self):
        result = _compute_corporate_tax({})
        assert result["corporate_tax_estimate"] == 0

    def test_effective_rate_is_reasonable(self):
        pnl = {"ebitda": 1_000_000}
        result = _compute_corporate_tax(pnl)
        # Effective rate should be slightly below CORPORATE_TAX_RATE due to depreciation
        assert 0 < result["effective_rate"] < CORPORATE_TAX_RATE * 100

    def test_required_keys_present(self):
        pnl = {"ebitda": 1_000_000}
        result = _compute_corporate_tax(pnl)
        for key in ("taxable_income", "corporate_tax_estimate", "effective_rate"):
            assert key in result


# ── Payment Calendar Tests ─────────────────────────────────────────────────────

class TestBuildPaymentCalendar:

    def _sample_vat(self, payable: int = 100_000) -> dict:
        return {"output_vat": 200_000, "input_vat": 100_000, "net_vat_payable": payable}

    def _sample_withholding(self, withholding: int = 50_000, ssi: int = 112_500) -> dict:
        return {
            "salary_base": 333_333,
            "income_tax_withholding": withholding,
            "ssi_employer": ssi,
            "total_payroll_tax": withholding + ssi,
        }

    def _sample_corp_tax(self, estimate: int = 237_500) -> dict:
        return {"taxable_income": 950_000, "corporate_tax_estimate": estimate, "effective_rate": 23.75}

    def test_vat_due_date_is_28th_of_next_month(self):
        cal = _build_payment_calendar(
            self._sample_vat(), self._sample_withholding(0, 0),
            self._sample_corp_tax(0), "2024-01"
        )
        vat_entry = next(e for e in cal if e["type"] == "KDV (VAT)")
        assert vat_entry["due_date"] == "2024-02-28"

    def test_withholding_due_date_is_26th_of_next_month(self):
        cal = _build_payment_calendar(
            self._sample_vat(0), self._sample_withholding(),
            self._sample_corp_tax(0), "2024-01"
        )
        entry = next(e for e in cal if e["type"] == "Stopaj (Withholding Tax)")
        assert entry["due_date"] == "2024-02-26"

    def test_sgi_included_when_positive(self):
        cal = _build_payment_calendar(
            self._sample_vat(0), self._sample_withholding(),
            self._sample_corp_tax(0), "2024-01"
        )
        types = [e["type"] for e in cal]
        assert "SGK İşveren Payı" in types

    def test_quarterly_tax_included_in_quarter_month(self):
        """March (month 3) is a quarter-end — quarterly tax should appear."""
        cal = _build_payment_calendar(
            self._sample_vat(0), self._sample_withholding(0, 0),
            self._sample_corp_tax(), "2024-03"
        )
        types = [e["type"] for e in cal]
        assert "Geçici Vergi" in types

    def test_quarterly_tax_not_in_non_quarter_month(self):
        """February is not a quarter-end — no quarterly tax."""
        cal = _build_payment_calendar(
            self._sample_vat(0), self._sample_withholding(0, 0),
            self._sample_corp_tax(), "2024-02"
        )
        types = [e["type"] for e in cal]
        assert "Geçici Vergi" not in types

    def test_december_wraps_to_january(self):
        cal = _build_payment_calendar(
            self._sample_vat(), self._sample_withholding(0, 0),
            self._sample_corp_tax(0), "2024-12"
        )
        vat_entry = next(e for e in cal if e["type"] == "KDV (VAT)")
        assert vat_entry["due_date"].startswith("2025-01")

    def test_calendar_sorted_by_due_date(self):
        cal = _build_payment_calendar(
            self._sample_vat(), self._sample_withholding(),
            self._sample_corp_tax(0), "2024-01"
        )
        dates = [e["due_date"] for e in cal]
        assert dates == sorted(dates)

    def test_zero_amounts_excluded(self):
        """Entries with zero amount should not appear in the calendar."""
        cal = _build_payment_calendar(
            {"output_vat": 0, "input_vat": 0, "net_vat_payable": 0},
            {"salary_base": 0, "income_tax_withholding": 0,
             "ssi_employer": 0, "total_payroll_tax": 0},
            {"taxable_income": 0, "corporate_tax_estimate": 0, "effective_rate": 0},
            "2024-01"
        )
        assert cal == []

    def test_invalid_reference_month_does_not_crash(self):
        """Bad reference_month string should fall back gracefully."""
        cal = _build_payment_calendar(
            self._sample_vat(), self._sample_withholding(0, 0),
            self._sample_corp_tax(0), "invalid"
        )
        assert isinstance(cal, list)

    def test_amount_in_calendar_matches_vat(self):
        vat = self._sample_vat(80_000)
        cal = _build_payment_calendar(
            vat, self._sample_withholding(0, 0),
            self._sample_corp_tax(0), "2024-05"
        )
        vat_entry = next(e for e in cal if e["type"] == "KDV (VAT)")
        assert vat_entry["amount"] == 80_000
