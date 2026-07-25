"""
Routing Engineering — CapabilityRouter

Solves the "run everything blindly" problem.
Currently all agents run in sequence regardless of whether data is available.
This wastes compute and produces empty/meaningless outputs.

CapabilityRouter inspects the current CFOState and decides:
  - Which agents CAN run (have required data)
  - Which agents SHOULD run (have sufficient data quality)
  - Which agents MUST be skipped (missing dependencies)
  - Execution order (respects dependency graph)

Design:
  - AgentCapability: declares what each agent needs and produces
  - RoutingDecision: the result of routing (run/skip/defer per agent)
  - CapabilityRouter: evaluates state and returns routing decisions
  - Dependency graph: ensures correct execution order

Usage:
    router = CapabilityRouter()

    decisions = router.route(state)
    for agent_name, decision in decisions.items():
        if decision.should_run:
            result = await run_agent(agent_name, state, config)
        else:
            logger.info("Skipping %s: %s", agent_name, decision.reason)

The router does NOT execute agents — it only decides.
Execution is the orchestrator's responsibility.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ── Routing decision ──────────────────────────────────────────────────────────

@dataclass
class RoutingDecision:
    agent: str
    should_run: bool
    reason: str
    priority: int = 5          # 1 (highest) – 10 (lowest)
    estimated_tokens: int = 0  # rough token budget for this agent
    dependencies_met: bool = True
    data_quality: float = 1.0  # 0.0 – 1.0


@dataclass
class RoutingPlan:
    """Full routing decision for all agents in one pipeline run."""
    decisions: dict[str, RoutingDecision]
    execution_order: list[str]   # agents that should_run, in priority order
    skipped: list[str]           # agents that should NOT run
    total_estimated_tokens: int

    @property
    def run_count(self) -> int:
        return len(self.execution_order)

    @property
    def skip_count(self) -> int:
        return len(self.skipped)

    def summary(self) -> str:
        run = ", ".join(self.execution_order) or "(none)"
        skip = ", ".join(self.skipped) or "(none)"
        return f"Run [{run}] | Skip [{skip}]"


# ── Capability declaration ────────────────────────────────────────────────────

@dataclass
class AgentCapability:
    """Declares what an agent needs and what it produces."""
    name: str
    # State keys required to have data (list of alternatives → any one suffices)
    requires_any: list[str] = field(default_factory=list)
    # State keys ALL required
    requires_all: list[str] = field(default_factory=list)
    # State keys this agent produces (used for downstream dependency)
    produces: list[str] = field(default_factory=list)
    # Agents that must run before this one
    depends_on: list[str] = field(default_factory=list)
    # Estimated token budget (for context planning)
    token_budget: int = 2048
    # Priority in execution order
    priority: int = 5
    # Custom validator: (state) -> (can_run: bool, reason: str)
    validator: Callable[[dict[str, Any]], tuple[bool, str]] | None = None


# ── Agent capability registry ─────────────────────────────────────────────────

def _has_data(state: dict[str, Any], key: str) -> bool:
    """Check if a state key exists and has meaningful data."""
    val = state.get(key)
    if val is None:
        return False
    if isinstance(val, list):
        return len(val) > 0
    if isinstance(val, dict):
        return len(val) > 0
    if isinstance(val, (int, float)):
        return True
    if isinstance(val, str):
        return len(val.strip()) > 0
    return bool(val)


def _transaction_quality(state: dict[str, Any]) -> float:
    """Estimate transaction data quality (0.0 – 1.0)."""
    txs = state.get("transactions") or []
    if not txs:
        return 0.0
    n = len(txs)
    if n < 5:
        return 0.3
    if n < 20:
        return 0.6
    if n < 50:
        return 0.8
    return 1.0


def _pnl_validator(state: dict[str, Any]) -> tuple[bool, str]:
    txs = state.get("transactions") or []
    if len(txs) < 3:
        return False, f"Too few transactions ({len(txs)}) for P&L."
    return True, ""


def _cashflow_validator(state: dict[str, Any]) -> tuple[bool, str]:
    txs = state.get("transactions") or []
    if len(txs) < 3:
        return False, f"Too few transactions ({len(txs)}) for cash flow."
    return True, ""


def _forecast_validator(state: dict[str, Any]) -> tuple[bool, str]:
    pnl = state.get("pnl") or {}
    cf = state.get("cashflow") or {}
    if not pnl.get("revenue"):
        return False, "P&L data missing — forecast requires revenue data."
    if not cf.get("monthly_series"):
        return False, "Monthly series missing — forecast requires cash flow data."
    return True, ""


def _budget_validator(state: dict[str, Any]) -> tuple[bool, str]:
    txs = state.get("transactions") or []
    if len(txs) < 5:
        return False, "Insufficient transactions for budget analysis."
    return True, ""


def _multiperiod_validator(state: dict[str, Any]) -> tuple[bool, str]:
    cf = state.get("cashflow") or {}
    series = cf.get("monthly_series") or []
    if len(series) < 3:
        return False, f"Only {len(series)} months of data — need ≥3 for trend analysis."
    return True, ""


def _anomaly_validator(state: dict[str, Any]) -> tuple[bool, str]:
    txs = state.get("transactions") or []
    if len(txs) < 5:
        return False, f"Too few transactions ({len(txs)}) for anomaly detection."
    return True, ""


# ── Built-in capability registry ──────────────────────────────────────────────

AGENT_CAPABILITIES: dict[str, AgentCapability] = {
    "data_ingestion": AgentCapability(
        name="data_ingestion",
        requires_any=["file_path", "raw_text"],
        produces=["transactions", "raw_text"],
        priority=1,
        token_budget=1024,
    ),
    "pnl_agent": AgentCapability(
        name="pnl_agent",
        requires_all=["transactions"],
        produces=["pnl"],
        depends_on=["data_ingestion"],
        priority=2,
        token_budget=3072,
        validator=_pnl_validator,
    ),
    "cashflow_agent": AgentCapability(
        name="cashflow_agent",
        requires_all=["transactions"],
        produces=["cashflow"],
        depends_on=["data_ingestion"],
        priority=2,
        token_budget=3072,
        validator=_cashflow_validator,
    ),
    "forecast_agent": AgentCapability(
        name="forecast_agent",
        requires_all=["pnl", "cashflow"],
        produces=["forecast"],
        depends_on=["pnl_agent", "cashflow_agent"],
        priority=3,
        token_budget=3072,
        validator=_forecast_validator,
    ),
    "anomaly_agent": AgentCapability(
        name="anomaly_agent",
        requires_all=["transactions"],
        produces=["anomalies"],
        depends_on=["data_ingestion"],
        priority=3,
        token_budget=2048,
        validator=_anomaly_validator,
    ),
    "budget_agent": AgentCapability(
        name="budget_agent",
        requires_all=["transactions"],
        produces=["budget"],
        depends_on=["pnl_agent"],
        priority=4,
        token_budget=2048,
        validator=_budget_validator,
    ),
    "tax_agent": AgentCapability(
        name="tax_agent",
        requires_all=["transactions", "pnl"],
        produces=["tax"],
        depends_on=["pnl_agent"],
        priority=4,
        token_budget=2048,
    ),
    "multi_period_agent": AgentCapability(
        name="multi_period_agent",
        requires_all=["cashflow"],
        produces=["multi_period"],
        depends_on=["cashflow_agent"],
        priority=4,
        token_budget=2048,
        validator=_multiperiod_validator,
    ),
    "alert_agent": AgentCapability(
        name="alert_agent",
        requires_any=["pnl", "cashflow", "forecast"],
        produces=["triggered_alerts"],
        depends_on=["pnl_agent", "cashflow_agent", "forecast_agent"],
        priority=5,
        token_budget=1024,
    ),
    "report_agent": AgentCapability(
        name="report_agent",
        requires_any=["pnl", "cashflow"],
        produces=["report_paths", "dashboard_json"],
        depends_on=["pnl_agent", "cashflow_agent"],
        priority=9,
        token_budget=512,
    ),
}


# ── CapabilityRouter ──────────────────────────────────────────────────────────

class CapabilityRouter:
    """
    Inspects CFOState and decides which agents should run.

    Decision logic per agent:
    1. Check requires_all — all must have data in state
    2. Check requires_any — at least one must have data
    3. Check depends_on — all dependencies must be in completed set
    4. Run optional custom validator
    5. Check data quality threshold
    """

    def __init__(
        self,
        capabilities: dict[str, AgentCapability] | None = None,
        min_data_quality: float = 0.3,
    ) -> None:
        self.capabilities = capabilities or AGENT_CAPABILITIES
        self.min_data_quality = min_data_quality

    def _evaluate_agent(
        self,
        cap: AgentCapability,
        state: dict[str, Any],
        completed: set[str],
    ) -> RoutingDecision:
        """Evaluate whether a single agent should run."""

        # 1. Check requires_all
        for key in cap.requires_all:
            if not _has_data(state, key):
                return RoutingDecision(
                    agent=cap.name,
                    should_run=False,
                    reason=f"Required state key missing: '{key}'",
                    priority=cap.priority,
                    dependencies_met=False,
                )

        # 2. Check requires_any
        if cap.requires_any:
            found = any(_has_data(state, k) for k in cap.requires_any)
            if not found:
                return RoutingDecision(
                    agent=cap.name,
                    should_run=False,
                    reason=f"None of {cap.requires_any} available in state.",
                    priority=cap.priority,
                    dependencies_met=False,
                )

        # 3. Check depends_on (only if those agents are in the registry)
        missing_deps = [
            dep for dep in cap.depends_on
            if dep in self.capabilities and dep not in completed
        ]
        if missing_deps:
            return RoutingDecision(
                agent=cap.name,
                should_run=False,
                reason=f"Dependencies not yet completed: {missing_deps}",
                priority=cap.priority,
                dependencies_met=False,
            )

        # 4. Custom validator
        if cap.validator:
            ok, reason = cap.validator(state)
            if not ok:
                return RoutingDecision(
                    agent=cap.name,
                    should_run=False,
                    reason=reason,
                    priority=cap.priority,
                    dependencies_met=True,
                )

        # 5. Data quality check
        quality = _transaction_quality(state)
        if quality < self.min_data_quality:
            return RoutingDecision(
                agent=cap.name,
                should_run=False,
                reason=f"Data quality too low: {quality:.1f} < {self.min_data_quality}",
                priority=cap.priority,
                data_quality=quality,
            )

        return RoutingDecision(
            agent=cap.name,
            should_run=True,
            reason="All checks passed.",
            priority=cap.priority,
            estimated_tokens=cap.token_budget,
            dependencies_met=True,
            data_quality=quality,
        )

    def route(
        self,
        state: dict[str, Any],
        requested_agents: list[str] | None = None,
        already_completed: set[str] | None = None,
    ) -> RoutingPlan:
        """
        Compute the full routing plan for a pipeline run.

        Parameters
        ----------
        state : dict
            Current CFOState.
        requested_agents : list[str], optional
            Subset of agents to consider. If None, considers all registered agents.
        already_completed : set[str], optional
            Agents already completed in this run (for dependency tracking).
        """
        completed = already_completed or set()
        agents_to_check = requested_agents or list(self.capabilities.keys())

        decisions: dict[str, RoutingDecision] = {}

        # Topological sort: process in priority order, track completed
        # Simple approach: multiple passes until stable
        sorted_agents = sorted(
            agents_to_check,
            key=lambda a: self.capabilities.get(a, AgentCapability(a)).priority,
        )

        for agent_name in sorted_agents:
            cap = self.capabilities.get(agent_name)
            if cap is None:
                decisions[agent_name] = RoutingDecision(
                    agent=agent_name,
                    should_run=True,
                    reason="Unknown agent — no capability registered, allowing through.",
                    priority=5,
                )
                continue

            decision = self._evaluate_agent(cap, state, completed)
            decisions[agent_name] = decision

            # If we're doing a simulated run (for planning), mark as "completed"
            # so downstream agents can see their deps met
            if decision.should_run:
                completed = completed | {agent_name}

        # Build execution order (only agents that should run, sorted by priority)
        run_agents = [
            name for name in sorted_agents
            if decisions.get(name, RoutingDecision(name, False, "")).should_run
        ]
        skip_agents = [
            name for name in sorted_agents
            if not decisions.get(name, RoutingDecision(name, False, "")).should_run
        ]

        total_tokens = sum(
            decisions[a].estimated_tokens for a in run_agents if a in decisions
        )

        plan = RoutingPlan(
            decisions=decisions,
            execution_order=run_agents,
            skipped=skip_agents,
            total_estimated_tokens=total_tokens,
        )

        logger.info(
            "CapabilityRouter: %d run, %d skip | tokens≈%d | %s",
            plan.run_count, plan.skip_count, total_tokens, plan.summary(),
        )

        return plan

    def can_run(self, agent: str, state: dict[str, Any]) -> tuple[bool, str]:
        """Quick check for a single agent."""
        cap = self.capabilities.get(agent)
        if cap is None:
            return True, "No capability registered."
        decision = self._evaluate_agent(cap, state, set())
        return decision.should_run, decision.reason


# ── Module-level default instance ────────────────────────────────────────────

_default_router = CapabilityRouter()


def get_capability_router() -> CapabilityRouter:
    return _default_router
