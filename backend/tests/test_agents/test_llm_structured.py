"""
Tests for llm_structured.py — template-based fallback functions.
No LLM key needed — all tests use _is_placeholder_key=True path.
"""
import pytest
from app.services.llm_structured import (
    PnLNarrative,
    CashFlowNarrative,
    ForecastNarrative,
    ActionItem,
    RiskItem,
    _pnl_narrative_template,
    _cashflow_narrative_template,
    _forecast_narrative_template,
    _is_placeholder_key,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _pnl(
    revenue: int = 2_000_000,
    cogs: int = 600_000,
    gross_profit: int = 1_400_000,
    gross_margin: float = 0.70,
    total_opex: int = 800_000,
    ebitda: int = 600_000,
    ebitda_margin: float = 0.30,
    net_income: int = 400_000,
    net_margin: float = 0.20,
    tax: int = 0,
    loan_payments: int = 0,
) -> dict:
    return {
        "revenue": revenue,
        "cogs": cogs,
        "gross_profit": gross_profit,
        "gross_margin": gross_margin,
        "total_opex": total_opex,
        "ebitda": ebitda,
        "ebitda_margin": ebitda_margin,
        "net_income": net_income,
        "net_margin": net_margin,
        "tax": tax,
        "loan_payments": loan_payments,
        "opex": {"salary": 500_000, "rent": 150_000, "marketing": 150_000},
    }


def _cashflow(operating: int = 300_000, net_change: int = 200_000) -> dict:
    return {
        "operating": operating,
        "investing": 0,
        "financing": 0,
        "net_change": net_change,
        "monthly_series": [],
        "alerts": [],
    }


def _forecast(base_net: int = 2_400_000, runway: int | None = None) -> dict:
    return {
        "scenarios": {
            "optimistic": {"label": "İyimser", "twelve_month_net": 4_000_000, "runway_months": None, "months": []},
            "base":       {"label": "Baz",     "twelve_month_net": base_net,    "runway_months": runway,  "months": []},
            "pessimistic":{"label": "Kötümser","twelve_month_net": -200_000,    "runway_months": 3,       "months": []},
        },
        "alerts": [],
    }


# ── _is_placeholder_key ────────────────────────────────────────────────────────

class TestIsPlaceholderKey:

    def test_empty_string_is_placeholder(self):
        assert _is_placeholder_key("") is True

    def test_dev_placeholder_is_placeholder(self):
        assert _is_placeholder_key("sk-dev-placeholder") is True

    def test_demo_placeholder_is_placeholder(self):
        assert _is_placeholder_key("sk-demo-placeholder-replace-with-real-key") is True

    def test_dev_prefix_is_placeholder(self):
        assert _is_placeholder_key("sk-dev-mykey123") is True

    def test_real_key_is_not_placeholder(self):
        assert _is_placeholder_key("sk-abc123realkey") is False

    def test_deepseek_key_is_not_placeholder(self):
        assert _is_placeholder_key("sk-1a2b3c4d5e6f7g8h") is False


# ── PnLNarrative schema ───────────────────────────────────────────────────────

class TestPnLNarrativeSchema:

    def test_valid_construction(self):
        n = PnLNarrative(
            summary="Test özet",
            risks=[RiskItem(risk="Risk 1", severity="high")],
            actions=[ActionItem(action="Eylem 1", urgency="immediate", impact="high")],
        )
        assert n.summary == "Test özet"
        assert len(n.risks) == 1
        assert len(n.actions) == 1

    def test_to_text_contains_summary(self):
        n = PnLNarrative(
            summary="Gelir tablosu sağlıklı.",
            actions=[ActionItem(action="Giderleri azaltın.")],
        )
        text = n.to_text()
        assert "Gelir tablosu sağlıklı." in text

    def test_to_text_contains_risks(self):
        n = PnLNarrative(
            summary="Özet.",
            risks=[RiskItem(risk="Brüt marj düşük", severity="critical")],
            actions=[ActionItem(action="Fiyatları artırın.")],
        )
        text = n.to_text()
        assert "Brüt marj düşük" in text
        assert "CRITICAL" in text or "critical" in text.lower()

    def test_to_text_contains_actions(self):
        n = PnLNarrative(
            summary="Özet.",
            actions=[
                ActionItem(action="Birinci eylem."),
                ActionItem(action="İkinci eylem."),
            ],
        )
        text = n.to_text()
        assert "Birinci eylem." in text
        assert "İkinci eylem." in text

    def test_defaults_are_empty_lists(self):
        n = PnLNarrative(
            summary="Özet.",
            actions=[ActionItem(action="Eylem.")],
        )
        assert n.highlights == []
        assert n.risks == []
        assert n.benchmark_note is None


# ── _pnl_narrative_template ───────────────────────────────────────────────────

class TestPnLNarrativeTemplate:

    def test_returns_pnl_narrative(self):
        result = _pnl_narrative_template(_pnl())
        assert isinstance(result, PnLNarrative)

    def test_summary_not_empty(self):
        result = _pnl_narrative_template(_pnl())
        assert len(result.summary) > 20

    def test_has_at_least_one_action(self):
        result = _pnl_narrative_template(_pnl())
        assert len(result.actions) >= 1

    def test_healthy_pnl_no_critical_risks(self):
        result = _pnl_narrative_template(_pnl(
            gross_margin=0.60, net_margin=0.20, net_income=400_000
        ))
        critical = [r for r in result.risks if r.severity == "critical"]
        assert len(critical) == 0

    def test_low_gross_margin_triggers_risk(self):
        result = _pnl_narrative_template(_pnl(gross_margin=0.08))
        risk_severities = [r.severity for r in result.risks]
        assert "critical" in risk_severities

    def test_negative_net_income_triggers_critical_risk(self):
        result = _pnl_narrative_template(_pnl(net_income=-100_000, net_margin=-0.05))
        risk_severities = [r.severity for r in result.risks]
        assert "critical" in risk_severities

    def test_benchmark_note_present(self):
        result = _pnl_narrative_template(_pnl())
        assert result.benchmark_note is not None
        assert "%" in result.benchmark_note

    def test_to_text_returns_string(self):
        result = _pnl_narrative_template(_pnl())
        text = result.to_text()
        assert isinstance(text, str)
        assert len(text) > 50

    def test_actions_have_impact_and_urgency(self):
        result = _pnl_narrative_template(_pnl())
        for action in result.actions:
            assert action.urgency in ("immediate", "this_week", "this_month", "normal")
            assert action.impact in ("high", "medium", "low")

    def test_action_count_within_bounds(self):
        result = _pnl_narrative_template(_pnl())
        assert 1 <= len(result.actions) <= 4


# ── _cashflow_narrative_template ──────────────────────────────────────────────

class TestCashFlowNarrativeTemplate:

    def test_returns_cashflow_narrative(self):
        result = _cashflow_narrative_template(_cashflow())
        assert isinstance(result, CashFlowNarrative)

    def test_summary_not_empty(self):
        result = _cashflow_narrative_template(_cashflow())
        assert len(result.summary) > 20

    def test_liquidity_assessment_present(self):
        result = _cashflow_narrative_template(_cashflow())
        assert result.liquidity_assessment

    def test_positive_cashflow_is_safe(self):
        result = _cashflow_narrative_template(_cashflow(operating=500_000, net_change=300_000))
        assert "güvenli" in result.liquidity_assessment.lower()

    def test_negative_operating_is_risky(self):
        result = _cashflow_narrative_template(_cashflow(operating=-100_000, net_change=-100_000))
        assert "riskli" in result.liquidity_assessment.lower()

    def test_negative_cf_has_immediate_action(self):
        result = _cashflow_narrative_template(_cashflow(operating=-100_000))
        urgent_actions = [a for a in result.actions if a.urgency == "immediate"]
        assert len(urgent_actions) >= 1

    def test_alerts_converted_to_risks(self):
        cf = _cashflow()
        cf["alerts"] = [
            {"level": "critical", "message": "Nakit tükenme riski var"},
        ]
        result = _cashflow_narrative_template(cf)
        assert len(result.risks) >= 1

    def test_to_text_returns_string(self):
        result = _cashflow_narrative_template(_cashflow())
        assert isinstance(result.to_text(), str)


# ── _forecast_narrative_template ──────────────────────────────────────────────

class TestForecastNarrativeTemplate:

    def test_returns_forecast_narrative(self):
        result = _forecast_narrative_template(_forecast())
        assert isinstance(result, ForecastNarrative)

    def test_summary_not_empty(self):
        result = _forecast_narrative_template(_forecast())
        assert len(result.summary) > 20

    def test_base_scenario_comment_present(self):
        result = _forecast_narrative_template(_forecast())
        assert result.base_scenario_comment

    def test_has_key_assumptions(self):
        result = _forecast_narrative_template(_forecast())
        assert len(result.key_assumptions) >= 1

    def test_negative_base_net_triggers_risk(self):
        result = _forecast_narrative_template(_forecast(base_net=-500_000))
        # Negative base scenario should mention sustainability risk
        all_text = result.summary + result.base_scenario_comment
        assert any(word in all_text.lower() for word in ["negatif", "zarar", "sürdürülebilir"])

    def test_short_runway_triggers_risk(self):
        result = _forecast_narrative_template(_forecast(runway=2))
        risk_severities = [r.severity for r in result.risks]
        assert "critical" in risk_severities

    def test_no_risk_for_healthy_forecast(self):
        # Build a forecast with no short runways in any scenario
        healthy_forecast = {
            "scenarios": {
                "optimistic": {"label": "İyimser", "twelve_month_net": 6_000_000, "runway_months": None, "months": []},
                "base":       {"label": "Baz",     "twelve_month_net": 4_000_000, "runway_months": None, "months": []},
                "pessimistic":{"label": "Kötümser","twelve_month_net": 1_000_000, "runway_months": None, "months": []},
            },
            "alerts": [],
        }
        result = _forecast_narrative_template(healthy_forecast)
        critical = [r for r in result.risks if r.severity == "critical"]
        assert len(critical) == 0

    def test_has_actions(self):
        result = _forecast_narrative_template(_forecast())
        assert len(result.actions) >= 1

    def test_to_text_returns_string(self):
        result = _forecast_narrative_template(_forecast())
        text = result.to_text()
        assert isinstance(text, str)
        assert len(text) > 50


# ── Integration: async get_* functions (template path) ────────────────────────

import asyncio
from unittest.mock import MagicMock


def _mock_settings(key: str = "sk-dev-placeholder") -> MagicMock:
    s = MagicMock()
    s.openai_api_key = key
    s.llm_model = "deepseek-chat"
    s.llm_base_url = "https://api.deepseek.com"
    return s


def _run(coro):
    """Run async coroutine in a new event loop (Python 3.10+ compatible)."""
    return asyncio.run(coro)


class TestAsyncNarrativeFunctions:
    """These tests use the template path (placeholder key)."""

    def test_get_pnl_narrative_template_path(self):
        from app.services.llm_structured import get_pnl_narrative
        result = _run(get_pnl_narrative(_pnl(), _mock_settings()))
        assert isinstance(result, PnLNarrative)
        assert len(result.summary) > 0

    def test_get_cashflow_narrative_template_path(self):
        from app.services.llm_structured import get_cashflow_narrative
        result = _run(get_cashflow_narrative(_cashflow(), _mock_settings()))
        assert isinstance(result, CashFlowNarrative)
        assert len(result.summary) > 0

    def test_get_forecast_narrative_template_path(self):
        from app.services.llm_structured import get_forecast_narrative
        result = _run(get_forecast_narrative(_forecast(), _mock_settings()))
        assert isinstance(result, ForecastNarrative)
        assert len(result.summary) > 0

    def test_to_text_produces_non_empty_string(self):
        from app.services.llm_structured import get_pnl_narrative
        narrative = _run(get_pnl_narrative(_pnl(), _mock_settings()))
        text = narrative.to_text()
        assert len(text) > 100
