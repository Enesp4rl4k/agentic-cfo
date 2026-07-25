"""
Tests for report_agent.py — pure function _build_dashboard_json (no LLM, no disk I/O).
"""
import pytest
from app.agents.report_agent import _build_dashboard_json, _fmt


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_state(
    revenue: int = 2_000_000,
    net_income: int = 400_000,
    gross_margin: float = 0.70,
    net_margin: float = 0.20,
    cogs: int = 600_000,
    gross_profit: int = 1_400_000,
    ebitda: int = 600_000,
    ebitda_margin: float = 0.30,
    operating_cf: int = 300_000,
    net_change_cf: int = 200_000,
    runway: int | None = 8,
    transactions: list | None = None,
) -> dict:
    state: dict = {
        "pnl": {
            "revenue": revenue,
            "cogs": cogs,
            "gross_profit": gross_profit,
            "gross_margin": gross_margin,
            "ebitda": ebitda,
            "ebitda_margin": ebitda_margin,
            "net_income": net_income,
            "net_margin": net_margin,
            "opex": {"salary": 500_000, "rent": 150_000},
            "narrative": "Good quarter.",
        },
        "cashflow": {
            "operating": operating_cf,
            "investing": 0,
            "financing": 0,
            "net_change": net_change_cf,
            "monthly_series": [],
            "alerts": [],
        },
        "forecast": {
            "scenarios": {
                "base": {
                    "runway_months": runway,
                    "twelve_month_net": 2_400_000,
                    "months": [],
                },
                "optimistic": {"runway_months": None, "twelve_month_net": 4_000_000, "months": []},
                "pessimistic": {"runway_months": 3, "twelve_month_net": -200_000, "months": []},
            },
            "alerts": [],
            "narrative": "Stable forecast.",
        },
        "transactions": transactions or [],
    }
    return state


# ── _fmt ──────────────────────────────────────────────────────────────────────

class TestFmt:

    def test_converts_cents_to_currency_units(self):
        assert _fmt(1_000_000) == pytest.approx(10_000.0)

    def test_zero_is_zero(self):
        assert _fmt(0) == 0.0

    def test_negative_value(self):
        assert _fmt(-500_000) == pytest.approx(-5_000.0)


# ── _build_dashboard_json ─────────────────────────────────────────────────────

class TestBuildDashboardJson:

    def test_returns_dict(self):
        result = _build_dashboard_json(_make_state())
        assert isinstance(result, dict)

    def test_required_top_level_keys(self):
        result = _build_dashboard_json(_make_state())
        for key in ("generated_at", "kpis", "pnl", "cashflow",
                    "forecast", "recent_transactions", "transaction_count"):
            assert key in result

    def test_generated_at_is_iso_string(self):
        result = _build_dashboard_json(_make_state())
        assert isinstance(result["generated_at"], str)
        assert "T" in result["generated_at"]  # ISO 8601

    # ── KPIs ──────────────────────────────────────────────────────────────────

    def test_kpis_is_list(self):
        result = _build_dashboard_json(_make_state())
        assert isinstance(result["kpis"], list)

    def test_kpi_revenue_present(self):
        result = _build_dashboard_json(_make_state())
        labels = [k["label"] for k in result["kpis"]]
        assert "Revenue" in labels

    def test_kpi_net_income_present(self):
        result = _build_dashboard_json(_make_state())
        labels = [k["label"] for k in result["kpis"]]
        assert "Net Income" in labels

    def test_kpi_cash_runway_present_when_runway_set(self):
        result = _build_dashboard_json(_make_state(runway=8))
        labels = [k["label"] for k in result["kpis"]]
        assert "Cash Runway" in labels

    def test_kpi_cash_runway_absent_when_runway_none(self):
        result = _build_dashboard_json(_make_state(runway=None))
        labels = [k["label"] for k in result["kpis"]]
        assert "Cash Runway" not in labels

    def test_kpi_revenue_value_in_currency_units(self):
        result = _build_dashboard_json(_make_state(revenue=2_000_000))
        kpi = next(k for k in result["kpis"] if k["label"] == "Revenue")
        assert kpi["value"] == pytest.approx(20_000.0)

    def test_kpi_has_format_field(self):
        result = _build_dashboard_json(_make_state())
        for kpi in result["kpis"]:
            assert "format" in kpi
            assert kpi["format"] in ("currency", "percent", "months", "number")

    # ── P&L ───────────────────────────────────────────────────────────────────

    def test_pnl_revenue_converted(self):
        result = _build_dashboard_json(_make_state(revenue=2_000_000))
        assert result["pnl"]["revenue"] == pytest.approx(20_000.0)

    def test_pnl_gross_margin_as_ratio(self):
        result = _build_dashboard_json(_make_state(gross_margin=0.70))
        assert result["pnl"]["gross_margin"] == pytest.approx(0.70)

    def test_pnl_opex_converted(self):
        result = _build_dashboard_json(_make_state())
        assert result["pnl"]["opex"]["salary"] == pytest.approx(5_000.0)

    def test_pnl_narrative_preserved(self):
        result = _build_dashboard_json(_make_state())
        assert result["pnl"]["narrative"] == "Good quarter."

    def test_pnl_required_keys(self):
        result = _build_dashboard_json(_make_state())
        for key in ("revenue", "cogs", "gross_profit", "gross_margin",
                    "ebitda", "ebitda_margin", "net_income", "net_margin",
                    "opex", "narrative"):
            assert key in result["pnl"]

    # ── Cash Flow ─────────────────────────────────────────────────────────────

    def test_cashflow_operating_converted(self):
        result = _build_dashboard_json(_make_state(operating_cf=300_000))
        assert result["cashflow"]["operating"] == pytest.approx(3_000.0)

    def test_cashflow_net_change_converted(self):
        result = _build_dashboard_json(_make_state(net_change_cf=200_000))
        assert result["cashflow"]["net_change"] == pytest.approx(2_000.0)

    # ── Forecast ──────────────────────────────────────────────────────────────

    def test_forecast_scenarios_present(self):
        result = _build_dashboard_json(_make_state())
        assert "scenarios" in result["forecast"]

    def test_forecast_all_three_scenarios(self):
        result = _build_dashboard_json(_make_state())
        scenarios = result["forecast"]["scenarios"]
        assert set(scenarios.keys()) >= {"optimistic", "base", "pessimistic"}

    # ── Transactions ──────────────────────────────────────────────────────────

    def test_recent_transactions_limited_to_20(self):
        txs = [
            {"transaction_date": f"2024-01-{i:02d}", "amount_cents": 1_000, "type": "expense"}
            for i in range(1, 26)  # 25 transactions
        ]
        result = _build_dashboard_json(_make_state(transactions=txs))
        assert len(result["recent_transactions"]) <= 20

    def test_transaction_count_reflects_total(self):
        txs = [{"transaction_date": "2024-01-01", "amount_cents": 1_000, "type": "expense"}] * 10
        result = _build_dashboard_json(_make_state(transactions=txs))
        assert result["transaction_count"] == 10

    def test_recent_transactions_sorted_most_recent_first(self):
        txs = [
            {"transaction_date": "2024-01-01", "amount_cents": 100, "type": "expense"},
            {"transaction_date": "2024-03-01", "amount_cents": 200, "type": "expense"},
            {"transaction_date": "2024-02-01", "amount_cents": 150, "type": "expense"},
        ]
        result = _build_dashboard_json(_make_state(transactions=txs))
        dates = [t["transaction_date"] for t in result["recent_transactions"]]
        assert dates == sorted(dates, reverse=True)

    # ── Edge cases ────────────────────────────────────────────────────────────

    def test_empty_state_does_not_crash(self):
        result = _build_dashboard_json({})
        assert isinstance(result, dict)

    def test_missing_pnl_key_defaults_to_zero(self):
        state = _make_state()
        del state["pnl"]
        result = _build_dashboard_json(state)
        assert result["pnl"]["revenue"] == 0.0

    def test_no_forecast_no_runway_kpi(self):
        state = _make_state()
        del state["forecast"]
        result = _build_dashboard_json(state)
        labels = [k["label"] for k in result["kpis"]]
        assert "Cash Runway" not in labels
