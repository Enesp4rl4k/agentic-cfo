"""
COO Agent kernel types -- mirrors CMO/CTO state pattern, operations domain.

COOState is threaded through all COO LangGraph nodes.

Data inputs (what COO agents consume):
  - process_csv:   Business process data (cycle time, throughput, WIP)
  - resource_csv:  Headcount & productivity data (utilization, output per FTE)
  - sla_csv:       Customer SLA & service delivery data (breach rate, NPS, response time)

All monetary amounts stored as INTEGER (cents), same as CFO/CTO/CMO convention.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Shared audit type
# ---------------------------------------------------------------------------

@dataclass
class COOStepLog:
    step: str
    ok: bool
    detail: str | None = None
    confidence: float | None = None  # 0-1


# ---------------------------------------------------------------------------
# COO Run State -- threaded through all LangGraph nodes
# ---------------------------------------------------------------------------

class COOState(TypedDict, total=False):
    # -- Input ----------------------------------------------------------------
    job_id: str
    company_name: str | None
    period: str | None

    # Raw input data (at least one required)
    process_csv: str | None     # process performance export
    resource_csv: str | None    # headcount/productivity data
    sla_csv: str | None         # SLA & service delivery data

    # -- ProcessAgent ---------------------------------------------------------
    processes: dict[str, Any] | None
    # {
    #   total_processes: int,
    #   avg_cycle_time_days: float,
    #   avg_throughput_per_week: float,
    #   avg_wip: float,                     # work in progress (Little's Law)
    #   bottleneck_process: str,
    #   efficiency_score: float,            # 0-10 (10 = fully efficient)
    #   by_process: {name: {cycle_time, throughput, wip, efficiency}},
    #   overloaded_processes: [{name, wip, cycle_time, reason}],
    #   alerts: [{level, message}],
    #   narrative: str
    # }

    # -- ResourceAgent --------------------------------------------------------
    resources: dict[str, Any] | None
    # {
    #   total_headcount: int,
    #   avg_utilization_rate: float,        # 0-1
    #   revenue_per_fte_cents: int,         # if revenue available
    #   output_per_fte: float,              # units/tasks per FTE
    #   overutilized_teams: [{team, utilization, burnout_risk}],
    #   underutilized_teams: [{team, utilization, opportunity}],
    #   by_department: {dept: {headcount, utilization, output}},
    #   alerts: [{level, message}],
    #   narrative: str
    # }

    # -- SLAAgent -------------------------------------------------------------
    sla: dict[str, Any] | None
    # {
    #   total_tickets: int,
    #   sla_breach_count: int,
    #   sla_breach_rate: float,             # 0-1
    #   avg_response_time_hours: float,
    #   avg_resolution_time_hours: float,
    #   avg_nps_score: float,               # -100 to 100
    #   by_tier: {tier: {tickets, breaches, breach_rate, avg_response}},
    #   recurring_issues: [{issue, count, pct}],
    #   trend: "improving" | "stable" | "degrading",
    #   alerts: [{level, message}],
    #   narrative: str
    # }

    # -- COO Summary ----------------------------------------------------------
    coo_summary: dict[str, Any] | None
    # {
    #   overall_ops_score: float,           # 0-10
    #   operational_efficiency_score: float,
    #   top_risks: [{domain, severity, message}],
    #   quick_wins: [{action, estimated_impact, effort}],
    #   narrative: str
    # }

    # Run control
    logs: list[COOStepLog]
    min_confidence: float
    awaiting_review: bool
    halted: bool
    error: str | None


# ---------------------------------------------------------------------------
# Skill result
# ---------------------------------------------------------------------------

@dataclass
class COOSkillResult:
    ok: bool
    patch: dict[str, Any] = field(default_factory=dict)
    confidence: float | None = None
    needs_review: bool = False
    halt: bool = False
    detail: str | None = None


# ---------------------------------------------------------------------------
# Run config
# ---------------------------------------------------------------------------

@dataclass
class COORunConfig:
    dry_run: bool = False
    require_review: bool = True
    auto_proceed_min_confidence: float = 0.80


DEFAULT_COO_RUN_CONFIG = COORunConfig()


# ---------------------------------------------------------------------------
# Routing constants
# ---------------------------------------------------------------------------

COO_ROUTE_PROCESS = "process"
COO_ROUTE_HOLD    = "hold_for_review"
COO_ROUTE_END     = "__end__"
COO_ROUTE_SUMMARY = "coo_summary"
