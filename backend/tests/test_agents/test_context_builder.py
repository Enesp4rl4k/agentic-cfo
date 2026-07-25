"""
Tests for ContextBuilder — context engineering layer.
Pure function tests, no LLM, no DB.
"""
import pytest
from app.services.context_builder import (
    ContextBuilder,
    ContextResult,
    _count_tokens,
    _summarise_transactions,
    _summarise_pnl,
    _summarise_cashflow,
    _summarise_forecast,
    _summarise_anomalies,
    _summarise_alerts,
    get_context_builder,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_transactions(n: int = 10) -> list[dict]:
    return [
        {
            "id": f"tx-{i}",
            "transaction_date": f"2024-{(i % 12) + 1:02d}-01",
            "type": "income" if i % 3 == 0 else "expense",
            "category": "revenue" if i % 3 == 0 else "salary",
            "vendor": f"Vendor {i}",
            "description": f"Transaction {i}",
            "amount_cents": (i + 1) * 10_000,
        }
        for i in range(n)
    ]


def _make_pnl() -> dict:
    return {
        "revenue": 480_000_00,
        "cogs": 144_000_00,
        "gross_profit": 336_000_00,
        "gross_margin": 0.70,
        "opex": {"salary": 120_000_00, "rent": 24_000_00, "marketing": 18_000_00},
        "ebitda": 174_000_00,
        "ebitda_margin": 0.36,
        "net_income": 144_000_00,
        "net_margin": 0.30,
    }


def _make_cashflow() -> dict:
    return {
        "operating": 120_000_00,
        "investing": -24_000_00,
        "financing": -6_000_00,
        "net_change": 90_000_00,
        "monthly_series": [
            {"month": f"2024-{m:02d}", "in": 40_000_00, "out": 32_500_00, "net": 7_500_00}
            for m in range(1, 13)
        ],
        "alerts": [],
    }


def _make_forecast() -> dict:
    return {
        "scenarios": {
            "optimistic":  {"label": "Optimist",  "twelve_month_net": 180_000_00, "runway_months": 18},
            "base":        {"label": "Baz",        "twelve_month_net": 120_000_00, "runway_months": 14},
            "pessimistic": {"label": "Pesimist",   "twelve_month_net": -20_000_00, "runway_months": 3},
        }
    }


def _make_state() -> dict:
    return {
        "transactions": _make_transactions(30),
        "pnl": _make_pnl(),
        "cashflow": _make_cashflow(),
        "forecast": _make_forecast(),
        "anomalies": [],
        "triggered_alerts": [],
    }


# ── Token counting ────────────────────────────────────────────────────────────

class TestTokenCounting:
    def test_empty_string(self):
        assert _count_tokens("") >= 0

    def test_single_word(self):
        assert _count_tokens("hello") >= 1

    def test_longer_text_more_tokens(self):
        short = _count_tokens("short text")
        long_ = _count_tokens("short text " * 100)
        assert long_ > short

    def test_returns_int(self):
        result = _count_tokens("test")
        assert isinstance(result, int)


# ── Summarise helpers ─────────────────────────────────────────────────────────

class TestSummariseTransactions:
    def test_empty(self):
        result = _summarise_transactions([])
        assert "no transactions" in result

    def test_has_header(self):
        result = _summarise_transactions(_make_transactions(5))
        assert "date,type,category" in result

    def test_truncates_to_max_rows(self):
        result = _summarise_transactions(_make_transactions(100), max_rows=10)
        lines = [l for l in result.split("\n") if l.strip() and not l.startswith("date")]
        # 10 data rows + possibly 1 truncation note
        assert len(lines) <= 12

    def test_truncation_note_present(self):
        result = _summarise_transactions(_make_transactions(50), max_rows=5)
        assert "truncated" in result

    def test_sorts_by_amount(self):
        txs = [
            {"transaction_date": "2024-01-01", "type": "expense", "category": "rent",
             "vendor": "A", "amount_cents": 100},
            {"transaction_date": "2024-01-02", "type": "income", "category": "revenue",
             "vendor": "B", "amount_cents": 999_999},
        ]
        result = _summarise_transactions(txs, sort_by_amount=True)
        lines = result.split("\n")
        # B (bigger) should appear before A
        b_pos = next((i for i, l in enumerate(lines) if "B" in l), 999)
        a_pos = next((i for i, l in enumerate(lines) if "A" in l), 999)
        assert b_pos < a_pos


class TestSummarisePnL:
    def test_empty(self):
        assert "no P&L" in _summarise_pnl({})

    def test_contains_revenue(self):
        result = _summarise_pnl(_make_pnl())
        assert "Revenue" in result

    def test_contains_net_income(self):
        result = _summarise_pnl(_make_pnl())
        assert "Net Income" in result

    def test_contains_margin_pct(self):
        result = _summarise_pnl(_make_pnl())
        assert "%" in result


class TestSummariseCashflow:
    def test_empty(self):
        assert "no cash flow" in _summarise_cashflow({})

    def test_contains_operating(self):
        result = _summarise_cashflow(_make_cashflow())
        assert "Operating" in result

    def test_shows_last_3_months(self):
        result = _summarise_cashflow(_make_cashflow())
        assert "Last 3 months" in result


class TestSummariseForecast:
    def test_empty(self):
        assert "no forecast" in _summarise_forecast({})

    def test_shows_scenarios(self):
        result = _summarise_forecast(_make_forecast())
        assert "optimistic" in result.lower() or "Optimist" in result

    def test_shows_12mo_net(self):
        result = _summarise_forecast(_make_forecast())
        assert "12mo_net" in result


class TestSummariseAnomalies:
    def test_empty(self):
        assert "no anomalies" in _summarise_anomalies([])

    def test_shows_total(self):
        anomalies = [
            {"severity": "critical", "title": "Duplicate payment", "anomaly_type": "duplicate_payment"},
            {"severity": "high",     "title": "Unusual amount",    "anomaly_type": "unusual_amount"},
        ]
        result = _summarise_anomalies(anomalies)
        assert "Total: 2" in result

    def test_critical_first(self):
        anomalies = [
            {"severity": "low",      "title": "Low issue",      "anomaly_type": "round_number"},
            {"severity": "critical", "title": "Critical issue",  "anomaly_type": "duplicate_payment"},
        ]
        result = _summarise_anomalies(anomalies)
        crit_pos = result.index("Critical issue")
        low_pos  = result.index("Low issue")
        assert crit_pos < low_pos


class TestSummariseAlerts:
    def test_empty(self):
        assert "no alerts" in _summarise_alerts([])

    def test_shows_total(self):
        alerts = [
            {"level": "critical", "message": "Cashflow critical"},
            {"level": "warning",  "message": "Revenue drop"},
        ]
        result = _summarise_alerts(alerts)
        assert "Total: 2" in result


# ── ContextBuilder ────────────────────────────────────────────────────────────

class TestContextBuilder:
    def test_default_budget(self):
        cb = ContextBuilder()
        assert cb.budget == 4096

    def test_custom_budget(self):
        cb = ContextBuilder(budget=1000)
        assert cb.budget == 1000

    def test_get_context_builder_default(self):
        cb = get_context_builder()
        assert cb.budget == 4096

    def test_get_context_builder_custom(self):
        cb = get_context_builder(budget=2048)
        assert cb.budget == 2048

    def test_assemble_respects_budget(self):
        cb = ContextBuilder(budget=50)
        # One tiny slice, one huge slice
        slices = [
            ("small", "Hi"),
            ("huge",  "word " * 10000),
        ]
        result = cb._assemble(slices)
        assert result.token_count <= 50 + 20  # some tolerance for overhead
        assert "small" in result.slices_included
        assert "huge" not in result.slices_included or result.truncated

    def test_assemble_returns_context_result(self):
        cb = ContextBuilder(budget=4096)
        result = cb._assemble([("a", "Hello world")])
        assert isinstance(result, ContextResult)

    def test_context_result_utilization(self):
        cb = ContextBuilder(budget=4096)
        result = cb._assemble([("a", "Hello")])
        assert 0.0 <= result.utilization <= 1.0

    def test_context_result_not_truncated_when_fits(self):
        cb = ContextBuilder(budget=4096)
        result = cb._assemble([("a", "short text")])
        assert not result.truncated

    def test_context_result_truncated_when_overflow(self):
        cb = ContextBuilder(budget=10)
        result = cb._assemble([("a", "short"), ("b", "word " * 1000)])
        assert result.truncated

    def test_build_pnl_context(self):
        cb = ContextBuilder(budget=4096)
        state = _make_state()
        result = cb.build_pnl_context(state, sector="tech")
        assert isinstance(result.text, str)
        assert len(result.text) > 0
        assert result.token_count > 0
        assert result.token_count <= result.budget + 50  # small tolerance

    def test_build_pnl_context_with_benchmark(self):
        cb = ContextBuilder(budget=4096)
        state = _make_state()
        result = cb.build_pnl_context(state, benchmark_lines="gross_margin: 70% vs 65%")
        assert "benchmark" in result.text.lower() or "benchmark" in str(result.slices_included).lower()

    def test_build_cashflow_context(self):
        cb = ContextBuilder(budget=3072)
        result = cb.build_cashflow_context(_make_state())
        assert isinstance(result.text, str)
        assert result.token_count <= result.budget + 50

    def test_build_forecast_context(self):
        cb = ContextBuilder(budget=3072)
        result = cb.build_forecast_context(_make_state())
        assert isinstance(result.text, str)
        assert result.token_count <= result.budget + 50

    def test_build_anomaly_context(self):
        state = _make_state()
        state["anomalies"] = [
            {"severity": "critical", "anomaly_type": "duplicate_payment",
             "title": "Dup", "description": "Duplicate", "confidence": 0.95},
        ]
        cb = ContextBuilder(budget=4096)
        result = cb.build_anomaly_context(state)
        assert isinstance(result.text, str)

    def test_build_synthesis_context(self):
        cb = ContextBuilder(budget=4096)
        result = cb.build_synthesis_context(_make_state())
        assert isinstance(result.text, str)
        assert result.token_count <= result.budget + 50

    def test_pnl_context_includes_instruction(self):
        cb = ContextBuilder(budget=4096)
        result = cb.build_pnl_context(_make_state())
        # Instruction slice should always fit in a 4096 budget
        assert any("instruction" in s for s in result.slices_included)

    def test_very_tight_budget_still_returns_result(self):
        cb = ContextBuilder(budget=20)
        result = cb.build_pnl_context(_make_state())
        # Even with tight budget, should return something
        assert isinstance(result, ContextResult)
        assert result.truncated  # most slices dropped

    def test_empty_transactions_handled(self):
        cb = ContextBuilder(budget=4096)
        state = _make_state()
        state["transactions"] = []
        result = cb.build_pnl_context(state)
        assert isinstance(result.text, str)

    def test_empty_state_handled(self):
        cb = ContextBuilder(budget=4096)
        result = cb.build_pnl_context({})
        assert isinstance(result.text, str)
