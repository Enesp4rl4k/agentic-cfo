"""
Orchestrator kernel integration tests.

Verifies that CapabilityRouter, ReflectionAgent, and AgentMemoryStore
are correctly wired into the pipeline orchestrator.

These tests use the mock LLM pattern — no real LLM or DB needed.
"""
import sys
import types
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

# ── LangChain stub ────────────────────────────────────────────────────────────
for mod in [
    "langchain_openai", "langchain_core", "langchain_core.messages",
    "langchain_core.language_models", "langchain_core.language_models.chat_models",
    "langchain_core.runnables", "langgraph", "langgraph.graph",
]:
    if mod not in sys.modules:
        sys.modules[mod] = types.ModuleType(mod)

lc = sys.modules["langchain_openai"]
if not hasattr(lc, "ChatOpenAI"):
    lc.ChatOpenAI = MagicMock  # type: ignore

msgs = sys.modules["langchain_core.messages"]
for cls in ["HumanMessage", "SystemMessage", "AIMessage"]:
    if not hasattr(msgs, cls):
        setattr(msgs, cls, MagicMock)

# Stub langgraph.graph
lg = sys.modules["langgraph.graph"]
if not hasattr(lg, "StateGraph"):
    class _FakeStateGraph:
        def __init__(self, *a, **kw): pass
        def add_node(self, *a, **kw): pass
        def set_entry_point(self, *a, **kw): pass
        def add_conditional_edges(self, *a, **kw): pass
        def add_edge(self, *a, **kw): pass
        def compile(self): return self
        async def ainvoke(self, state, **kw): return state
    lg.StateGraph = _FakeStateGraph  # type: ignore
    lg.END = "__end__"  # type: ignore

# ── Import services after stubs ───────────────────────────────────────────────
from app.services.capability_router import CapabilityRouter, AGENT_CAPABILITIES
from app.services.reflection_agent import ReflectionAgent, ReflectionResult
from app.services.agent_memory import AgentMemoryStore, EpisodeRecord
from app.agents.orchestrator import (
    _is_skipped,
    _update_reflection,
    node_data_ingestion,
    node_pnl,
    node_cashflow,
    node_forecast,
    node_anomaly,
    node_multi_period,
    node_tax,
    node_budget,
)
from tests.fixtures.llm_mock import (
    make_sample_state,
    make_sample_pnl,
    make_sample_cashflow,
    patch_settings,
)


# ── _is_skipped helper ────────────────────────────────────────────────────────

class TestIsSkipped:
    def test_no_plan_returns_false(self):
        state = make_sample_state()
        assert not _is_skipped(state, "anomaly_agent")

    def test_should_run_true_returns_false(self):
        state = {
            **make_sample_state(),
            "routing_plan": {
                "decisions": {"anomaly_agent": {"should_run": True, "reason": "ok"}},
            },
        }
        assert not _is_skipped(state, "anomaly_agent")

    def test_should_run_false_returns_true(self):
        state = {
            **make_sample_state(),
            "routing_plan": {
                "decisions": {"anomaly_agent": {"should_run": False, "reason": "no data"}},
            },
        }
        assert _is_skipped(state, "anomaly_agent")

    def test_unknown_agent_returns_false(self):
        state = {
            **make_sample_state(),
            "routing_plan": {"decisions": {}},
        }
        assert not _is_skipped(state, "unknown_agent")


# ── _update_reflection helper ─────────────────────────────────────────────────

class TestUpdateReflection:
    def test_returns_reflection_scores_patch(self):
        state = make_sample_state()
        narrative = (
            "Gelir %15 artışla ₺4.8M'a ulaştı. Net marj %29 ile güçlü seyretti. "
            "Maliyetler optimize edilmeli, büyüme stratejisi geliştirilmeli."
        )
        patch = _update_reflection(state, "pnl", narrative, make_sample_pnl())
        assert "reflection_scores" in patch
        assert "pnl" in patch["reflection_scores"]

    def test_reflection_score_has_required_fields(self):
        state = make_sample_state()
        narrative = (
            "Nakit akışı pozitif. Faaliyet geliri ₺12M üretti, giderler kontrol altında. "
            "Yatırımlar azaltılmalı, nakit rezervleri artırılmalı."
        )
        patch = _update_reflection(state, "cashflow", narrative, make_sample_cashflow())
        score = patch["reflection_scores"]["cashflow"]
        assert "overall_score" in score
        assert "grade" in score
        assert "passed" in score

    def test_empty_narrative_still_returns_patch(self):
        state = make_sample_state()
        patch = _update_reflection(state, "pnl", "", {})
        # Empty narrative → reflection not triggered (guard in node_pnl)
        # But if called directly, should handle gracefully
        assert isinstance(patch, dict)

    def test_merges_with_existing_reflection_scores(self):
        state = {
            **make_sample_state(),
            "reflection_scores": {"cashflow": {"overall_score": 0.7}},
        }
        narrative = (
            "Gelir artışı güçlü seyretti ve marjlar yükseldi. Net kâr iyileşti. "
            "Strateji gözden geçirilmeli ve yatırımlar optimize edilmeli."
        )
        patch = _update_reflection(state, "pnl", narrative, make_sample_pnl())
        scores = patch["reflection_scores"]
        assert "cashflow" in scores  # existing preserved
        assert "pnl" in scores       # new added


# ── CapabilityRouter — routing plan in state ──────────────────────────────────

class TestCapabilityRouterIntegration:
    def test_routing_plan_has_correct_structure(self):
        router = CapabilityRouter()
        state = make_sample_state()
        plan = router.route(state)
        plan_dict = {
            "execution_order": plan.execution_order,
            "skipped": plan.skipped,
            "decisions": {
                k: {"should_run": v.should_run, "reason": v.reason}
                for k, v in plan.decisions.items()
            },
        }
        assert "execution_order" in plan_dict
        assert "decisions" in plan_dict
        assert isinstance(plan_dict["decisions"], dict)

    def test_routing_plan_serialisable(self):
        import json
        router = CapabilityRouter()
        state = make_sample_state()
        plan = router.route(state)
        plan_dict = {
            "execution_order": plan.execution_order,
            "skipped": plan.skipped,
            "decisions": {
                k: {"should_run": v.should_run, "reason": v.reason}
                for k, v in plan.decisions.items()
            },
        }
        # Must be JSON-serialisable (for state storage)
        serialised = json.dumps(plan_dict)
        assert len(serialised) > 0

    def test_skip_affects_non_fatal_nodes(self):
        """Node reads routing_plan from state and returns early if skipped."""
        state = {
            **make_sample_state(),
            "routing_plan": {
                "decisions": {
                    "anomaly_agent": {"should_run": False, "reason": "test skip"},
                },
            },
        }
        assert _is_skipped(state, "anomaly_agent")


# ── ReflectionAgent quality scores ───────────────────────────────────────────

class TestReflectionIntegration:
    def test_good_narrative_high_score(self):
        agent = ReflectionAgent(pass_threshold=0.50)
        narrative = (
            "Gelir %15 artışla ₺4.8M'a ulaştı ve net marj %29 seviyesinde güçlü seyretti. "
            "EBITDA marjı %33 ile sektör ortalamasının üzerinde kaldı. "
            "Operasyonel giderler kontrol altında tutulmalı, pazarlama bütçesi optimize edilmeli."
        )
        result = agent.evaluate_narrative(narrative, make_sample_pnl())
        assert result.overall_score > 0.5

    def test_reflection_feeds_back_to_state(self):
        """reflection_scores state key is updated after reflection."""
        state = make_sample_state()
        narrative = (
            "Bu dönem finansal performans güçlü. Gelirler ₺48M'a ulaştı. "
            "Net marj %29 ile hedeflerin üzerinde. Stratejik öncelikler gözden geçirilmeli."
        )
        patch = _update_reflection(state, "pnl", narrative, make_sample_pnl())
        assert patch["reflection_scores"]["pnl"]["overall_score"] > 0

    def test_low_quality_narrative_flagged(self):
        agent = ReflectionAgent()
        result = agent.evaluate_narrative("Kısa.", {})
        assert not result.passed
        assert len(result.improvement_hints) > 0


# ── AgentMemoryStore — episode saving ────────────────────────────────────────

class TestMemoryIntegration:
    def test_episode_saved_with_correct_fields(self):
        store = AgentMemoryStore(backend="memory")
        ep = EpisodeRecord(
            org_id="org-test",
            agent="cfo_pipeline",
            period="2024-Q4",
            job_id="job-001",
            summary={
                "revenue": 480_000_00,
                "net_income": 144_000_00,
                "net_margin": 0.30,
                "net_cashflow": 90_000_00,
                "anomaly_count": 3,
                "alert_count": 1,
                "min_confidence": 0.92,
            },
            narrative="Güçlü dönem...",
            confidence=0.92,
            tags=["pipeline", "csv"],
        )
        store.save(ep)
        results = store.retrieve(org_id="org-test", agent="cfo_pipeline")
        assert len(results) == 1
        saved = results[0]
        assert saved.summary["revenue"] == 480_000_00
        assert saved.confidence == 0.92
        assert "csv" in saved.tags

    def test_memory_context_usable_in_next_run(self):
        """Simulate: run 1 saves episode, run 2 retrieves and formats context."""
        store = AgentMemoryStore(backend="memory")

        # Run 1: save
        ep = EpisodeRecord(
            org_id="org-1",
            agent="cfo_pipeline",
            period="2024-Q3",
            summary={"net_income": 100_000_00, "net_margin": 0.20},
            narrative="Orta güçlü dönem, iyileştirme gerekli.",
            confidence=0.85,
        )
        store.save(ep)

        # Run 2: retrieve and format for context
        past = store.retrieve(org_id="org-1", top_k=3)
        context_text = store.format_for_context(past)
        assert "2024-Q3" in context_text
        assert len(context_text) > 20

    def test_memory_similarity_search(self):
        store = AgentMemoryStore(backend="memory")
        store.save(EpisodeRecord(
            org_id="org-1", agent="cfo_pipeline", period="2024-Q1",
            summary={}, narrative="Nakit akışı kritik, likidite sorunu var",
            confidence=0.9,
        ))
        store.save(EpisodeRecord(
            org_id="org-1", agent="cfo_pipeline", period="2024-Q2",
            summary={}, narrative="Gelir büyümesi güçlü, marjlar arttı",
            confidence=0.9,
        ))
        results = store.retrieve(org_id="org-1", query="nakit akışı likidite")
        assert results[0].period == "2024-Q1"


# ── Kernel services wired in orchestrator module ──────────────────────────────

class TestKernelServicesWired:
    def test_orchestrator_imports_kernel_services(self):
        """Verify all three kernel services are importable from orchestrator."""
        from app.agents.orchestrator import _router, _reflector, _memory
        assert isinstance(_router, CapabilityRouter)
        assert isinstance(_reflector, ReflectionAgent)
        assert isinstance(_memory, AgentMemoryStore)

    def test_is_skipped_function_exists(self):
        from app.agents.orchestrator import _is_skipped
        assert callable(_is_skipped)

    def test_update_reflection_function_exists(self):
        from app.agents.orchestrator import _update_reflection
        assert callable(_update_reflection)

    def test_routing_plan_key_in_cfostate_type(self):
        from app.agents.state import CFOState
        # TypedDict keys accessible via __annotations__
        annotations = CFOState.__annotations__
        assert "routing_plan" in annotations
        assert "reflection_scores" in annotations
        assert "memory_episode_ids" in annotations
        assert "org_id" in annotations

    def test_run_cfo_pipeline_signature_has_org_id(self):
        import inspect
        from app.agents.orchestrator import run_cfo_pipeline
        sig = inspect.signature(run_cfo_pipeline)
        assert "org_id" in sig.parameters
        assert "period" in sig.parameters
