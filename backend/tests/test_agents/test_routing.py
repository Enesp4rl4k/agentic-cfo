"""
Tests for CapabilityRouter — routing engineering layer.
Pure tests, no LLM, no DB.
"""
import pytest
from app.services.capability_router import (
    CapabilityRouter,
    RoutingPlan,
    RoutingDecision,
    AgentCapability,
    AGENT_CAPABILITIES,
    get_capability_router,
    _has_data,
    _transaction_quality,
)


# ── _has_data helper ──────────────────────────────────────────────────────────

class TestHasData:
    def test_none_returns_false(self):
        assert not _has_data({}, "missing")

    def test_empty_list_returns_false(self):
        assert not _has_data({"txs": []}, "txs")

    def test_non_empty_list_returns_true(self):
        assert _has_data({"txs": [1, 2]}, "txs")

    def test_empty_dict_returns_false(self):
        assert not _has_data({"pnl": {}}, "pnl")

    def test_non_empty_dict_returns_true(self):
        assert _has_data({"pnl": {"revenue": 100}}, "pnl")

    def test_zero_int_returns_true(self):
        assert _has_data({"val": 0}, "val")

    def test_non_empty_string_returns_true(self):
        assert _has_data({"text": "hello"}, "text")

    def test_empty_string_returns_false(self):
        assert not _has_data({"text": ""}, "text")


# ── _transaction_quality helper ───────────────────────────────────────────────

class TestTransactionQuality:
    def test_no_transactions_zero(self):
        assert _transaction_quality({}) == 0.0

    def test_few_transactions_low(self):
        state = {"transactions": [{}] * 3}
        assert _transaction_quality(state) < 0.5

    def test_many_transactions_high(self):
        state = {"transactions": [{}] * 100}
        assert _transaction_quality(state) == 1.0

    def test_moderate_transactions_medium(self):
        state = {"transactions": [{}] * 25}
        q = _transaction_quality(state)
        assert 0.5 <= q < 1.0


# ── CapabilityRouter ──────────────────────────────────────────────────────────

def _make_full_state() -> dict:
    """State with all data present."""
    return {
        "file_path": "/tmp/test.csv",
        "transactions": [{"id": f"tx-{i}", "type": "income", "amount_cents": 10000} for i in range(30)],
        "pnl": {"revenue": 480_000_00, "net_income": 144_000_00, "net_margin": 0.30},
        "cashflow": {
            "operating": 120_000_00,
            "net_change": 90_000_00,
            "monthly_series": [{"month": f"2024-{i:02d}", "net": 7_500_00} for i in range(1, 7)],
        },
        "forecast": {"scenarios": {"base": {}, "optimistic": {}, "pessimistic": {}}},
    }


def _make_empty_state() -> dict:
    return {}


def _make_txs_only_state() -> dict:
    return {
        "transactions": [{"id": f"tx-{i}"} for i in range(20)],
    }


class TestCapabilityRouter:
    def test_returns_routing_plan(self):
        router = CapabilityRouter()
        plan = router.route(_make_full_state())
        assert isinstance(plan, RoutingPlan)

    def test_empty_state_skips_most_agents(self):
        router = CapabilityRouter()
        plan = router.route(_make_empty_state())
        # With no data, most agents should be skipped
        assert plan.skip_count > plan.run_count

    def test_full_state_runs_most_agents(self):
        router = CapabilityRouter()
        plan = router.route(_make_full_state())
        # With full state, most agents should run
        assert plan.run_count >= 3

    def test_txs_only_enables_pnl_and_cashflow(self):
        router = CapabilityRouter()
        # data_ingestion needs file_path; mark it as already_completed so
        # pnl/cashflow dependency is satisfied
        state = _make_txs_only_state()
        plan = router.route(
            state,
            already_completed={"data_ingestion"},
        )
        assert "pnl_agent" in plan.execution_order
        assert "cashflow_agent" in plan.execution_order

    def test_forecast_requires_pnl_and_cashflow(self):
        router = CapabilityRouter()
        # State with only transactions (no pnl/cashflow yet)
        plan = router.route(_make_txs_only_state())
        # forecast_agent should NOT run without pnl+cashflow data
        assert "forecast_agent" not in plan.execution_order

    def test_forecast_runs_with_full_state(self):
        router = CapabilityRouter()
        plan = router.route(_make_full_state())
        assert "forecast_agent" in plan.execution_order

    def test_execution_order_respects_priority(self):
        router = CapabilityRouter()
        plan = router.route(_make_full_state())
        # data_ingestion (priority 1) should come before report_agent (priority 9)
        order = plan.execution_order
        if "data_ingestion" in order and "report_agent" in order:
            assert order.index("data_ingestion") < order.index("report_agent")

    def test_pnl_runs_before_forecast(self):
        router = CapabilityRouter()
        plan = router.route(_make_full_state())
        order = plan.execution_order
        if "pnl_agent" in order and "forecast_agent" in order:
            assert order.index("pnl_agent") < order.index("forecast_agent")

    def test_decisions_dict_has_all_agents(self):
        router = CapabilityRouter()
        plan = router.route(_make_full_state())
        for agent in AGENT_CAPABILITIES:
            assert agent in plan.decisions

    def test_run_plus_skip_equals_total(self):
        router = CapabilityRouter()
        plan = router.route(_make_full_state())
        all_requested = list(AGENT_CAPABILITIES.keys())
        assert plan.run_count + plan.skip_count == len(all_requested)

    def test_total_estimated_tokens_positive(self):
        router = CapabilityRouter()
        plan = router.route(_make_full_state())
        assert plan.total_estimated_tokens > 0

    def test_summary_returns_string(self):
        router = CapabilityRouter()
        plan = router.route(_make_full_state())
        assert isinstance(plan.summary(), str)

    def test_requested_agents_subset(self):
        router = CapabilityRouter()
        plan = router.route(
            _make_full_state(),
            requested_agents=["pnl_agent", "cashflow_agent"],
        )
        assert set(plan.decisions.keys()) == {"pnl_agent", "cashflow_agent"}

    def test_already_completed_updates_deps(self):
        router = CapabilityRouter()
        # forecast requires pnl+cashflow. If those are in already_completed, forecast can run
        # even without their data in state (assuming the state was populated by them)
        state = {
            "transactions": [{}] * 20,
            "pnl": {"revenue": 100, "net_income": 10, "net_margin": 0.1},
            "cashflow": {
                "operating": 100,
                "net_change": 90,
                "monthly_series": [{"month": f"2024-{i:02d}", "net": 10} for i in range(1, 5)],
            },
        }
        plan = router.route(
            state,
            requested_agents=["forecast_agent"],
            already_completed={"pnl_agent", "cashflow_agent"},
        )
        assert "forecast_agent" in plan.execution_order

    def test_min_data_quality_filters_low_quality(self):
        router = CapabilityRouter(min_data_quality=0.9)
        # Only 3 transactions → quality ~0.3, below 0.9
        state = {"transactions": [{}] * 3}
        plan = router.route(state, requested_agents=["pnl_agent"])
        # pnl_agent should be skipped due to low data quality
        assert "pnl_agent" not in plan.execution_order

    def test_unknown_agent_allowed_through(self):
        router = CapabilityRouter()
        plan = router.route(
            _make_full_state(),
            requested_agents=["unknown_custom_agent"],
        )
        assert "unknown_custom_agent" in plan.execution_order

    def test_can_run_single_agent_true(self):
        router = CapabilityRouter()
        # anomaly_agent has no dependency on data_ingestion in can_run context
        # Use alert_agent which uses requires_any and no strict dep in can_run
        # Actually test an agent with no depends_on: use a custom cap
        custom_caps = {
            "standalone": AgentCapability(
                name="standalone",
                requires_all=["transactions"],
                produces=["result"],
                depends_on=[],   # no deps
                priority=5,
            )
        }
        router2 = CapabilityRouter(capabilities=custom_caps)
        ok, reason = router2.can_run("standalone", _make_txs_only_state())
        assert ok, f"Expected ok but got: {reason}"

    def test_can_run_single_agent_false_no_data(self):
        router = CapabilityRouter()
        ok, reason = router.can_run("pnl_agent", _make_empty_state())
        assert not ok
        assert len(reason) > 0

    def test_can_run_forecast_false_no_pnl(self):
        router = CapabilityRouter()
        ok, reason = router.can_run("forecast_agent", _make_txs_only_state())
        assert not ok

    def test_custom_capability_registered(self):
        custom_cap = AgentCapability(
            name="custom_agent",
            requires_all=["transactions"],
            produces=["custom_output"],
            priority=6,
            token_budget=512,
        )
        caps = {**AGENT_CAPABILITIES, "custom_agent": custom_cap}
        router = CapabilityRouter(capabilities=caps)
        plan = router.route(_make_txs_only_state(), requested_agents=["custom_agent"])
        assert "custom_agent" in plan.execution_order

    def test_get_capability_router_returns_instance(self):
        router = get_capability_router()
        assert isinstance(router, CapabilityRouter)

    def test_routing_decision_has_reason(self):
        router = CapabilityRouter()
        plan = router.route(_make_empty_state())
        for agent, decision in plan.decisions.items():
            if not decision.should_run:
                assert len(decision.reason) > 0
