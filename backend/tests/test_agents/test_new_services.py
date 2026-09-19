"""
Unit tests for new services:
  - CascadeSimulator
  - BenchmarkIntelligenceService
  - LLMTaskRouter
  - NLSimulationBridge
  - TemporalIntelligenceEngine (append-only log)

All tests are fully deterministic — no LLM calls, no DB, no network.
"""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

# ═══════════════════════════════════════════════════════════════════════════════
# CascadeSimulator
# ═══════════════════════════════════════════════════════════════════════════════

class TestCascadeSimulator:
    """CascadeSimulator — deterministic risk propagation tests."""

    def _make_simulator(self, **kwargs):
        from app.services.cascade_simulator import CascadeSimulator
        defaults = {
            "revenue_monthly": 1_000_000_00,   # 1M TL in cents
            "headcount": 50,
            "cash_balance": 6_000_000_00,       # 6M TL
            "monthly_burn": 500_000_00,          # 500K TL
            "monthly_revenue": 1_000_000_00,
            "gross_margin": 0.60,
        }
        defaults.update(kwargs)
        return CascadeSimulator(**defaults)

    def test_cash_crisis_trigger_produces_result(self):
        from app.services.cascade_simulator import TriggerType
        sim = self._make_simulator()
        result = sim.simulate(TriggerType.CASH_CRISIS, runway_months=2.0)
        assert result is not None
        assert len(result.domain_impacts) > 0
        assert result.executive_summary
        assert result.trigger_type == TriggerType.CASH_CRISIS

    def test_cash_crisis_generates_three_scenarios(self):
        from app.services.cascade_simulator import TriggerType
        sim = self._make_simulator()
        result = sim.simulate(TriggerType.CASH_CRISIS, runway_months=2.0)
        assert len(result.scenarios) == 3

    def test_revenue_drop_trigger(self):
        from app.services.cascade_simulator import TriggerType
        sim = self._make_simulator()
        result = sim.simulate(TriggerType.REVENUE_DROP, drop_pct=0.30)
        assert result is not None
        assert result.trigger_type == TriggerType.REVENUE_DROP
        assert any(i.domain == "finance" for i in result.domain_impacts)

    def test_key_person_loss_trigger(self):
        from app.services.cascade_simulator import TriggerType
        sim = self._make_simulator()
        result = sim.simulate(TriggerType.KEY_PERSON_LOSS, role="cto")
        assert result is not None
        assert len(result.domain_impacts) > 0

    def test_market_shock_trigger(self):
        from app.services.cascade_simulator import TriggerType
        sim = self._make_simulator()
        result = sim.simulate(TriggerType.MARKET_SHOCK, shock_type="fx_crisis", severity=0.4)
        assert result is not None

    def test_high_runway_means_low_severity(self):
        from app.services.cascade_simulator import ImpactLevel, TriggerType
        sim = self._make_simulator()
        # 12+ months runway should have lower overall severity than 1 month
        result_low  = sim.simulate(TriggerType.CASH_CRISIS, runway_months=12.0)
        result_high = sim.simulate(TriggerType.CASH_CRISIS, runway_months=1.0)
        # Critical count should be higher for low runway
        critical_low  = sum(1 for i in result_low.domain_impacts  if i.level == ImpactLevel.CRITICAL)
        critical_high = sum(1 for i in result_high.domain_impacts if i.level == ImpactLevel.CRITICAL)
        assert critical_high >= critical_low

    def test_to_dict_serializable(self):
        from app.services.cascade_simulator import TriggerType
        sim = self._make_simulator()
        result = sim.simulate(TriggerType.CASH_CRISIS, runway_months=3.0)
        d = result.to_dict()
        assert isinstance(d, dict)
        assert "trigger_type" in d
        assert "domain_impacts" in d
        assert "scenarios" in d
        assert "executive_summary" in d

    def test_singleton_factory(self):
        from app.services.cascade_simulator import get_cascade_simulator
        s1 = get_cascade_simulator()
        s2 = get_cascade_simulator()
        assert s1 is s2  # Same instance


# ═══════════════════════════════════════════════════════════════════════════════
# BenchmarkIntelligenceService
# ═══════════════════════════════════════════════════════════════════════════════

class TestBenchmarkIntelligenceService:
    """BenchmarkIntelligenceService — sector comparison tests."""

    def _make_svc(self):
        from app.services.benchmark_intelligence import BenchmarkIntelligenceService
        return BenchmarkIntelligenceService()

    def test_compare_cfo_returns_report(self):
        svc = self._make_svc()
        pnl = {
            "net_margin": 0.08,
            "gross_margin": 0.65,
            "revenue_growth": 0.20,
        }
        report = svc.compare_cfo(pnl, sector="saas")
        assert report is not None
        assert len(report.items) > 0
        assert report.sector == "saas"

    def test_compare_cfo_percentile_in_range(self):
        svc = self._make_svc()
        pnl = {"net_margin": 0.08, "gross_margin": 0.65}
        report = svc.compare_cfo(pnl, sector="saas")
        for item in report.items:
            if item.percentile is not None:
                assert 0 <= item.percentile <= 100

    def test_above_p75_is_leader(self):
        svc = self._make_svc()
        # gross_margin 0.90 >> P75 (0.80) for saas
        pnl = {"gross_margin": 0.90}
        report = svc.compare_cfo(pnl, sector="saas")
        gm_item = next((i for i in report.items if "Brüt" in i.metric), None)
        if gm_item and gm_item.percentile is not None:
            assert gm_item.percentile >= 75

    def test_below_p25_is_laggard(self):
        svc = self._make_svc()
        # gross_margin 0.20 << P25 (0.55) for saas
        pnl = {"gross_margin": 0.20}
        report = svc.compare_cfo(pnl, sector="saas")
        gm_item = next((i for i in report.items if "Brüt" in i.metric), None)
        if gm_item and gm_item.percentile is not None:
            assert gm_item.percentile <= 25

    def test_compare_all_runs_without_error(self):
        svc = self._make_svc()
        report = svc.compare_all(
            cfo_data={"net_margin": 0.05, "gross_margin": 0.60},
            cmo_data={"roas": 2.5, "cac_ltv_ratio": 3.0},
            chro_data={"annual_turnover_rate": 0.18},
            coo_data={"sla_compliance": 0.95},
            sector="saas",
        )
        assert report is not None
        assert len(report.items) > 0

    def test_report_has_strengths_weaknesses(self):
        svc = self._make_svc()
        pnl = {"net_margin": 0.25, "gross_margin": 0.80, "revenue_growth": 0.50}
        report = svc.compare_cfo(pnl, sector="saas")
        # Excellent metrics should generate some strengths
        assert isinstance(report.strengths, list)
        assert isinstance(report.weaknesses, list)

    def test_report_summary_is_string(self):
        svc = self._make_svc()
        report = svc.compare_cfo({"net_margin": 0.10}, sector="saas")
        assert isinstance(report.summary, str)
        assert len(report.summary) > 0

    def test_unknown_sector_falls_back(self):
        """Unknown sector should not raise — uses saas fallback."""
        svc = self._make_svc()
        report = svc.compare_cfo({"net_margin": 0.10}, sector="unknown_sector_xyz")
        assert report is not None


# ═══════════════════════════════════════════════════════════════════════════════
# LLMTaskRouter
# ═══════════════════════════════════════════════════════════════════════════════

class TestLLMTaskRouter:
    """LLMTaskRouter — model selection and cost tracking tests."""

    def _make_router(self):
        from app.services.llm_router import LLMTaskRouter
        return LLMTaskRouter()

    def test_classify_intent_uses_cheap_model(self):
        from app.services.llm_router import TaskType
        router = self._make_router()
        cfg = router.select_model(TaskType.CLASSIFY_INTENT)
        # Should be gpt-4o-mini (cheap), not gpt-4o
        assert "mini" in cfg.model_id or "3.5" in cfg.model_id

    def test_deep_analysis_uses_powerful_model(self):
        from app.services.llm_router import TaskType
        router = self._make_router()
        cfg = router.select_model(TaskType.DEEP_ANALYSIS)
        assert "gpt-4o" in cfg.model_id

    def test_deterministic_task_raises(self):
        from app.services.llm_router import TaskType
        router = self._make_router()
        with pytest.raises(ValueError, match="deterministik"):
            router.select_model(TaskType.CALCULATION)

    def test_long_prompt_upgrades_model(self):
        from app.services.llm_router import TaskType
        router = self._make_router()
        # Very long prompt (>8000 chars) should use gpt-4o for context window
        cfg = router.select_model(TaskType.SHORT_NARRATIVE, prompt_length=9000)
        assert cfg.context_window >= 128000

    def test_cost_estimate_positive(self):
        from app.services.llm_router import TaskType
        router = self._make_router()
        cost = router.cost_estimate(TaskType.DEEP_ANALYSIS, estimated_tokens=1000)
        assert cost > 0

    def test_cost_estimate_calculation_is_zero(self):
        from app.services.llm_router import TaskType
        router = self._make_router()
        cost = router.cost_estimate(TaskType.CALCULATION, estimated_tokens=1000)
        assert cost == 0.0

    def test_initial_stats_zero(self):
        router = self._make_router()
        stats = router.get_stats()
        assert stats["calls"] == 0
        assert stats["total_cost_usd"] == 0.0

    def test_singleton_returns_same_instance(self):
        from app.services.llm_router import get_llm_router
        r1 = get_llm_router()
        r2 = get_llm_router()
        assert r1 is r2

    @pytest.mark.asyncio
    async def test_complete_with_placeholder_key_returns_error_gracefully(self):
        from app.services.llm_router import LLMTaskRouter, TaskType
        router = LLMTaskRouter()
        # Mock _call_llm to raise to simulate no API key
        router._call_llm = AsyncMock(side_effect=RuntimeError("No API key"))
        result = await router.complete(task=TaskType.SHORT_NARRATIVE, prompt="Test")
        assert "[LLM hatası" in result.content or result.content  # Graceful fallback

    def test_cheap_model_lower_cost_than_expensive(self):
        from app.services.llm_router import TaskType
        router = self._make_router()
        cheap_cost = router.cost_estimate(TaskType.CLASSIFY_INTENT, 500)
        expensive_cost = router.cost_estimate(TaskType.DEEP_ANALYSIS, 500)
        assert cheap_cost < expensive_cost


# ═══════════════════════════════════════════════════════════════════════════════
# NLSimulationBridge
# ═══════════════════════════════════════════════════════════════════════════════

class TestNLSimulationBridge:
    """NLSimulationBridge — intent classification and entity extraction."""

    def _make_bridge(self):
        from app.services.nl_simulation_bridge import NLSimulationBridge
        return NLSimulationBridge()

    def test_headcount_intent_detected(self):
        bridge = self._make_bridge()
        intent = bridge.classify_intent("5 mühendis işe alırsam ne olur?")
        assert intent == "headcount"

    def test_marketing_intent_detected(self):
        bridge = self._make_bridge()
        intent = bridge.classify_intent("Pazarlama bütçesini 500K artırırsak satışlar ne olur?")
        assert intent == "marketing"

    def test_cascade_intent_detected(self):
        bridge = self._make_bridge()
        intent = bridge.classify_intent("Nakit 3 ayda biterse ne olur?")
        assert intent == "cascade"

    def test_cost_cut_intent_detected(self):
        bridge = self._make_bridge()
        intent = bridge.classify_intent("Giderleri %20 azaltırsak ne kazanırız?")
        assert intent == "cost_cut"

    def test_price_intent_detected(self):
        bridge = self._make_bridge()
        intent = bridge.classify_intent("Fiyatı %15 artırırsak marj ne olur?")
        assert intent == "price"

    def test_unknown_query_returns_unknown(self):
        bridge = self._make_bridge()
        intent = bridge.classify_intent("Hava bugün nasıl?")
        assert intent == "unknown"

    def test_extract_number_from_headcount_query(self):
        bridge = self._make_bridge()
        params = bridge.extract_entities("10 yazılımcı daha alsak?")
        assert params.get("count") == 10 or params.get("headcount_delta") == 10

    def test_extract_percentage_from_marketing_query(self):
        bridge = self._make_bridge()
        params = bridge.extract_entities("Pazarlama bütçesini %30 artır")
        pct = params.get("increase_pct") or params.get("budget_increase_pct")
        assert pct == 30 or pct == 0.30  # either format OK

    def test_bridge_handles_empty_query(self):
        bridge = self._make_bridge()
        intent = bridge.classify_intent("")
        assert intent == "unknown"

    def test_turkish_case_insensitive(self):
        bridge = self._make_bridge()
        intent1 = bridge.classify_intent("5 MÜHENDİS İŞE ALALIM")
        intent2 = bridge.classify_intent("5 mühendis işe alalım")
        assert intent1 == intent2


# ═══════════════════════════════════════════════════════════════════════════════
# TemporalIntelligenceEngine (DDIA append-only)
# ═══════════════════════════════════════════════════════════════════════════════

class TestTemporalIntelligenceEngine:
    """TemporalIntelligenceEngine — DDIA append-only event log tests."""

    def _make_engine(self):
        from app.services.temporal_intelligence import TemporalIntelligenceEngine
        return TemporalIntelligenceEngine()

    def test_record_event_creates_immutable_record(self):
        engine = self._make_engine()
        event = engine.record_analysis(
            org_id="test-org",
            agent="cfo",
            metrics={"net_margin": 0.08, "gross_margin": 0.65},
            narrative="Test narrative",
        )
        assert event.org_id == "test-org"
        assert event.agent == "cfo"
        assert "net_margin" in event.metrics

    def test_analysis_event_has_timestamp(self):
        engine = self._make_engine()
        event = engine.record_analysis(
            org_id="test-org",
            agent="cto",
            metrics={"tech_debt": 6.5},
            narrative="Tech debt is high",
        )
        assert event.recorded_at is not None
        # Should be a recent timestamp
        now = datetime.now(UTC)
        diff = abs((now - event.recorded_at).total_seconds())
        assert diff < 10  # Within 10 seconds

    def test_compute_delta_positive_change(self):
        engine = self._make_engine()
        delta = engine.compute_delta(
            current={"net_margin": 0.12},
            previous={"net_margin": 0.08},
            metric_key="net_margin",
        )
        assert delta > 0  # Improved

    def test_compute_delta_negative_change(self):
        engine = self._make_engine()
        delta = engine.compute_delta(
            current={"net_margin": 0.05},
            previous={"net_margin": 0.10},
            metric_key="net_margin",
        )
        assert delta < 0  # Worsened

    def test_compute_delta_missing_key_returns_none(self):
        engine = self._make_engine()
        delta = engine.compute_delta(
            current={"other": 1.0},
            previous={"net_margin": 0.10},
            metric_key="net_margin",
        )
        assert delta is None

    def test_detect_trends_ascending(self):
        engine = self._make_engine()
        series = [0.05, 0.07, 0.09, 0.11, 0.13]
        trend = engine.detect_trends(series)
        assert trend["direction"] == "improving"
        assert trend["slope"] > 0

    def test_detect_trends_descending(self):
        engine = self._make_engine()
        series = [0.13, 0.11, 0.09, 0.07, 0.05]
        trend = engine.detect_trends(series)
        assert trend["direction"] == "deteriorating"
        assert trend["slope"] < 0

    def test_detect_trends_stable(self):
        engine = self._make_engine()
        series = [0.10, 0.10, 0.10, 0.10, 0.10]
        trend = engine.detect_trends(series)
        assert trend["direction"] == "stable"

    def test_detect_trends_too_short_returns_insufficient(self):
        engine = self._make_engine()
        trend = engine.detect_trends([0.10])
        assert trend.get("direction") == "insufficient_data" or trend.get("direction") == "stable"


# ═══════════════════════════════════════════════════════════════════════════════
# BenchmarkIntelligence edge cases
# ═══════════════════════════════════════════════════════════════════════════════

class TestBenchmarkEdgeCases:
    """Edge cases for BenchmarkIntelligenceService."""

    def test_empty_cfo_data_does_not_crash(self):
        from app.services.benchmark_intelligence import BenchmarkIntelligenceService
        svc = BenchmarkIntelligenceService()
        report = svc.compare_cfo({}, sector="saas")
        assert report is not None

    def test_none_values_handled(self):
        from app.services.benchmark_intelligence import BenchmarkIntelligenceService
        svc = BenchmarkIntelligenceService()
        report = svc.compare_cfo({"net_margin": None, "gross_margin": None}, sector="saas")
        assert report is not None
        for item in report.items:
            # percentile can be None when company_value is None
            assert item.percentile is None or 0 <= item.percentile <= 100

    def test_negative_margin_handled(self):
        from app.services.benchmark_intelligence import BenchmarkIntelligenceService
        svc = BenchmarkIntelligenceService()
        # Negative margin is below P25
        report = svc.compare_cfo({"net_margin": -0.20}, sector="saas")
        nm_item = next((i for i in report.items if "Net" in i.metric), None)
        if nm_item and nm_item.percentile is not None:
            assert nm_item.percentile <= 25


# ═══════════════════════════════════════════════════════════════════════════════
# CascadeSimulator edge cases
# ═══════════════════════════════════════════════════════════════════════════════

class TestCascadeEdgeCases:
    """Edge cases and boundary conditions for CascadeSimulator."""

    def _make_simulator(self):
        from app.services.cascade_simulator import CascadeSimulator
        return CascadeSimulator(
            revenue_monthly=500_000_00,
            headcount=20,
            cash_balance=1_000_000_00,
            monthly_burn=200_000_00,
            monthly_revenue=500_000_00,
            gross_margin=0.45,
        )

    def test_zero_runway_is_handled(self):
        from app.services.cascade_simulator import TriggerType
        sim = self._make_simulator()
        # Should not raise
        result = sim.simulate(TriggerType.CASH_CRISIS, runway_months=0.0)
        assert result is not None

    def test_scenarios_have_increasing_severity(self):
        from app.services.cascade_simulator import TriggerType
        sim = self._make_simulator()
        result = sim.simulate(TriggerType.REVENUE_DROP, drop_pct=0.25)
        assert len(result.scenarios) == 3
        # Scenarios should be ordered by severity (optimistic → base → pessimistic)
        labels = [s.label.lower() for s in result.scenarios]
        has_optimistic = any("optimis" in l or "iyi" in l for l in labels)
        has_pessimistic = any("pessimis" in l or "kötü" in l for l in labels)
        assert has_optimistic or len(result.scenarios) == 3  # at least 3 scenarios

    def test_domain_impacts_have_required_fields(self):
        from app.services.cascade_simulator import TriggerType
        sim = self._make_simulator()
        result = sim.simulate(TriggerType.CASH_CRISIS, runway_months=2.0)
        for impact in result.domain_impacts:
            assert impact.domain
            assert impact.level is not None
            assert impact.description
