"""
Agent kernel types — domain-neutral.

Mirrors the pattern from listingpilot/packages/agent-kernel/src/types.ts
but adapted to Python and LangGraph.

An Agent is a LangGraph StateGraph. Each node is one Skill.
The confidence gate is a conditional edge before the first effect node.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Shared audit type (one entry per skill run)
# ---------------------------------------------------------------------------

@dataclass
class StepLog:
    step: str
    ok: bool
    detail: str | None = None
    confidence: float | None = None  # 0–1


# ---------------------------------------------------------------------------
# CFO Run State — threaded through all LangGraph nodes
# ---------------------------------------------------------------------------

class CFOState(TypedDict, total=False):
    # ── Input ─────────────────────────────────────────────────────────────────
    job_id: str
    file_path: str
    file_type: str          # pdf | xlsx | csv

    # ── Data Ingestion ────────────────────────────────────────────────────────
    raw_text: str
    transactions: list[dict[str, Any]]

    # ── P&L Agent ─────────────────────────────────────────────────────────────
    pnl: dict[str, Any]
    # {revenue, cogs, gross_profit, gross_margin, opex, total_opex,
    #  ebitda, ebitda_margin, net_income, net_margin, narrative}

    # ── Cash Flow Agent ───────────────────────────────────────────────────────
    cashflow: dict[str, Any]
    # {operating, investing, financing, net_change, monthly_series, narrative, alerts}

    # ── Forecast Agent ────────────────────────────────────────────────────────
    forecast: dict[str, Any]
    # {scenarios: {optimistic, base, pessimistic}, narrative, alerts}

    # ── Anomaly Agent ─────────────────────────────────────────────────────────
    anomalies: list[dict[str, Any]]
    anomaly_narrative: str

    # ── Budget Agent ──────────────────────────────────────────────────────────
    budget: dict[str, Any] | None
    # {items: [{category, budgeted, actual, variance, variance_pct}],
    #  total_budgeted, total_actual, total_variance, narrative}

    # ── Tax Agent ─────────────────────────────────────────────────────────────
    tax: dict[str, Any] | None
    # {vat_payable, withholding_tax, corporate_tax_estimate,
    #  payment_calendar: [{date, type, amount}], narrative}

    # ── Multi-Period Agent ────────────────────────────────────────────────────
    multi_period: dict[str, Any] | None
    # {mom: {revenue_pct, net_pct, ...}, yoy: {...}, trend_direction}

    # ── Alert Agent ───────────────────────────────────────────────────────────
    triggered_alerts: list[dict[str, Any]]
    # [{type, severity, message, threshold, actual_value, notified}]

    # ── Report Agent ──────────────────────────────────────────────────────────
    report_paths: dict[str, str]
    dashboard_json: dict[str, Any]

    # Run control
    logs: list[StepLog]
    min_confidence: float           # lowest confidence seen so far (starts at 1.0)
    awaiting_review: bool           # True → hold; needs human approval before effects
    halted: bool                    # True → stopped by error or explicit halt
    error: str | None               # last error message if halted

    # ── Kernel engineering metadata ───────────────────────────────────────────
    # CapabilityRouter: which agents to run (serialised RoutingPlan summary)
    routing_plan: dict[str, Any] | None
    # ReflectionAgent scores per agent narrative
    reflection_scores: dict[str, Any] | None
    # AgentMemory episode IDs saved in this run
    memory_episode_ids: list[str] | None
    # Org context for memory retrieval
    org_id: str | None


# ---------------------------------------------------------------------------
# Skill result — what each node returns as a state patch
# ---------------------------------------------------------------------------

@dataclass
class SkillResult:
    ok: bool
    patch: dict[str, Any] = field(default_factory=dict)
    confidence: float | None = None
    needs_review: bool = False
    halt: bool = False
    detail: str | None = None


# ---------------------------------------------------------------------------
# Run config — injected into every node via LangGraph config
# ---------------------------------------------------------------------------

@dataclass
class AgentRunConfig:
    dry_run: bool = False
    require_review: bool = True
    auto_proceed_min_confidence: float = 0.80


DEFAULT_RUN_CONFIG = AgentRunConfig()


# ---------------------------------------------------------------------------
# Routing constants (LangGraph edge names)
# ---------------------------------------------------------------------------

ROUTE_INGEST = "data_ingestion"
ROUTE_PNL = "pnl"
ROUTE_CASHFLOW = "cashflow"
ROUTE_FORECAST = "forecast"
ROUTE_REPORT = "report"
ROUTE_REVIEW_GATE = "review_gate"
ROUTE_END = "__end__"
ROUTE_HOLD = "hold_for_review"
