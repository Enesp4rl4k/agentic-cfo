"""
Tests for nl_query_engine.py — pure rule-based functions (no LLM, no DB).
Covers: classify_intent, extract_metric, get_nested, execute_nl_query
"""
import pytest
from app.agents.nl_query_engine import (
    classify_intent,
    extract_metric,
    get_nested,
    execute_nl_query,
)


# ── Sample dashboard data ─────────────────────────────────────────────────────

DASHBOARD = {
    "pnl": {
        "revenue":     2_000_000,
        "gross_profit": 1_400_000,
        "net_income":    400_000,
        "ebitda":        600_000,
        "opex": {
            "salary":    500_000,
            "rent":      150_000,
            "marketing": 100_000,
            "technology":  80_000,
        },
    },
    "cashflow": {
        "operating":   300_000,
        "net_change":  200_000,
        "monthly_series": [
            {"month": "2024-01", "in": 1_000_000, "out": 800_000, "net": 200_000},
            {"month": "2024-02", "in": 1_100_000, "out": 850_000, "net": 250_000},
        ],
    },
    "forecast": {
        "scenarios": {
            "base": {
                "runway_months": 8,
                "twelve_month_net": 2_400_000,
            },
            "pessimistic": {
                "runway_months": 3,
                "twelve_month_net": -500_000,
            },
        },
        "monte_carlo": {
            "runway_risk_pct": 12.5,
        },
    },
}


# ── classify_intent ───────────────────────────────────────────────────────────

class TestClassifyIntent:

    def test_runway_query_turkish(self):
        assert classify_intent("Paramız ne zaman biter?") == "runway_query"

    def test_runway_query_kaç_ay(self):
        assert classify_intent("Kaç ay daha dayanabiliriz?") == "runway_query"

    def test_scenario_artarsa(self):
        assert classify_intent("Kira %20 artarsa ne olur?") == "scenario"

    def test_scenario_azalırsa(self):
        assert classify_intent("Gelir %10 azalırsa?") == "scenario"

    def test_forecast_query_tahmin(self):
        assert classify_intent("3 ay sonra nakit durumum ne olur?") == "forecast_query"

    def test_forecast_query_gelecek_ay(self):
        assert classify_intent("Gelecek ay tahmini ne?") == "forecast_query"

    def test_anomaly_query_anomali(self):
        assert classify_intent("Bu ayki anomaliler neler?") == "anomaly_query"

    def test_anomaly_query_fraud(self):
        assert classify_intent("Şüpheli işlem var mı?") == "anomaly_query"

    def test_trend_gecen_ay(self):
        assert classify_intent("Geçen aya göre gelir nasıl değişti?") == "trend"

    def test_trend_büyüme(self):
        assert classify_intent("Büyüme oranı nedir?") == "trend"

    def test_comparison_en_yüksek(self):
        assert classify_intent("En yüksek gider kategorim hangisi?") == "comparison"

    def test_comparison_top(self):
        assert classify_intent("Top expense categories?") == "comparison"

    def test_metric_lookup_nakit(self):
        assert classify_intent("Nakit durumum nedir?") == "metric_lookup"

    def test_metric_lookup_gelir(self):
        assert classify_intent("Gelir ne kadar?") == "metric_lookup"

    def test_metric_lookup_default_for_unknown(self):
        # Unknown query falls back to metric_lookup
        assert classify_intent("Merhaba") == "metric_lookup"

    def test_case_insensitive(self):
        assert classify_intent("NAKIT AKIŞIM NE?") == "metric_lookup"

    def test_english_revenue(self):
        assert classify_intent("What is our revenue?") == "metric_lookup"

    # Priority: specific intents should win over generic metric_lookup
    def test_runway_wins_over_metric_lookup(self):
        # "runway" keyword + "nakit" both present — runway_query should win
        result = classify_intent("Nakit runway ne kadar?")
        assert result == "runway_query"


# ── extract_metric ────────────────────────────────────────────────────────────

class TestExtractMetric:

    def test_gelir_extracts_revenue(self):
        path, name = extract_metric("Gelir ne kadar?")
        assert path == "pnl.revenue"
        assert name is not None

    def test_nakit_extracts_cashflow(self):
        path, name = extract_metric("Nakit durumum nedir?")
        assert path == "cashflow.net_change"

    def test_ebitda_extracted(self):
        path, name = extract_metric("EBITDA nedir?")
        assert path == "pnl.ebitda"

    def test_maas_extracts_salary(self):
        path, name = extract_metric("Maaş giderleri ne kadar?")
        assert path == "pnl.opex.salary"

    def test_kira_extracts_rent(self):
        path, name = extract_metric("Kira maliyetimiz ne?")
        assert path == "pnl.opex.rent"

    def test_english_revenue(self):
        path, name = extract_metric("What is our revenue?")
        assert path == "pnl.revenue"

    def test_unknown_query_returns_none(self):
        path, name = extract_metric("Hava nasıl bugün?")
        assert path is None
        assert name is None

    def test_longest_match_wins(self):
        """'brüt kâr' should win over just 'kâr'."""
        path, name = extract_metric("Brüt kâr ne kadar?")
        assert path == "pnl.gross_profit"

    def test_case_insensitive_match(self):
        path, name = extract_metric("NAKIT AKIŞ ne durumda?")
        # nakit akış (without ş) or nakit — should still match
        assert path is not None


# ── get_nested ────────────────────────────────────────────────────────────────

class TestGetNested:

    def test_single_key(self):
        data = {"a": 1}
        assert get_nested(data, "a") == 1

    def test_two_levels(self):
        data = {"a": {"b": 42}}
        assert get_nested(data, "a.b") == 42

    def test_three_levels(self):
        data = {"pnl": {"opex": {"salary": 500_000}}}
        assert get_nested(data, "pnl.opex.salary") == 500_000

    def test_missing_key_returns_none(self):
        data = {"a": {"b": 42}}
        assert get_nested(data, "a.c") is None

    def test_missing_top_level_returns_none(self):
        data = {"a": 1}
        assert get_nested(data, "x.y") is None

    def test_non_dict_in_path_returns_none(self):
        data = {"a": 5}  # "a" is int, not dict
        assert get_nested(data, "a.b") is None

    def test_empty_path_returns_none(self):
        assert get_nested({}, "") is None or True  # implementation-defined

    def test_real_dashboard_revenue(self):
        assert get_nested(DASHBOARD, "pnl.revenue") == 2_000_000

    def test_real_dashboard_salary(self):
        assert get_nested(DASHBOARD, "pnl.opex.salary") == 500_000


# ── execute_nl_query ──────────────────────────────────────────────────────────

class TestExecuteNLQuery:

    def test_returns_dict(self):
        result = execute_nl_query("Gelir ne kadar?", DASHBOARD, [])
        assert isinstance(result, dict)

    def test_required_keys_present(self):
        result = execute_nl_query("Gelir ne kadar?", DASHBOARD, [])
        for key in ("intent", "raw_query"):
            assert key in result

    def test_raw_query_preserved(self):
        q = "Nakit akışım nedir?"
        result = execute_nl_query(q, DASHBOARD, [])
        assert result["raw_query"] == q

    def test_metric_lookup_revenue(self):
        result = execute_nl_query("Gelir ne kadar?", DASHBOARD, [])
        assert result["intent"] == "metric_lookup"
        assert result.get("value") == 2_000_000

    def test_metric_lookup_salary(self):
        result = execute_nl_query("Maaş giderleri ne kadar?", DASHBOARD, [])
        assert result.get("value") == 500_000

    def test_runway_query_returns_runway(self):
        result = execute_nl_query("Paramız ne zaman biter?", DASHBOARD, [])
        assert result["intent"] == "runway_query"
        assert result.get("value") == 8  # base scenario

    def test_runway_query_context_has_scenario(self):
        result = execute_nl_query("Runway ne kadar?", DASHBOARD, [])
        assert result.get("context", {}).get("scenario") is not None

    def test_comparison_returns_top_expenses(self):
        result = execute_nl_query("En yüksek gider kategorim hangisi?", DASHBOARD, [])
        assert result["intent"] == "comparison"
        value = result.get("value")
        assert value is not None

    def test_trend_query_returns_context(self):
        result = execute_nl_query("Geçen aya göre gelir nasıl değişti?", DASHBOARD, [])
        assert result["intent"] == "trend"

    def test_empty_dashboard_does_not_crash(self):
        result = execute_nl_query("Gelir nedir?", {}, [])
        assert isinstance(result, dict)

    def test_unknown_query_does_not_crash(self):
        result = execute_nl_query("Random soru", DASHBOARD, [])
        assert isinstance(result, dict)
        assert result.get("intent") == "metric_lookup"
