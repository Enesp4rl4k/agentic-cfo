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
    # Input
    job_id: str
    file_path: str
    file_type: str          # pdf | xlsx | csv

    # Data Ingestion outputs
    raw_text: str           # full extracted text from the document
    transactions: list[dict[str, Any]]  # parsed transaction dicts

    # P&L Agent outputs
    pnl: dict[str, Any]     # {revenue, cogs, gross_profit, opex, net_income, ...}

    # Cash Flow Agent outputs
    cashflow: dict[str, Any]  # {operating, investing, financing, net_change, ...}

    # Forecast Agent outputs
    forecast: dict[str, Any]  # {scenarios: {optimistic, base, pessimistic}, alerts: [...]}

    # Report Agent outputs
    report_paths: dict[str, str]   # {xlsx: "/path/...", pdf: "/path/..."}
    dashboard_json: dict[str, Any] # serialised summary for the frontend

    # Run control
    logs: list[StepLog]
    min_confidence: float           # lowest confidence seen so far (starts at 1.0)
    awaiting_review: bool           # True → hold; needs human approval before effects
    halted: bool                    # True → stopped by error or explicit halt
    error: str | None               # last error message if halted


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
