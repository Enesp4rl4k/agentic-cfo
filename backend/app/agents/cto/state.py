"""
CTO Agent kernel types — mirrors CFO state pattern, different domain.

CTOState is threaded through all CTO LangGraph nodes.
Each node returns a SkillResult (same as CFO) and patches the state.

Data inputs (what CTO agents consume):
  - cloud_billing_csv:   Raw cloud billing export (AWS Cost Explorer / GCP Billing)
  - git_log_text:        `git log --stat` output or GitHub API payload
  - incident_csv:        Incident log (PagerDuty / OpsGenie CSV export)
  - sprint_csv:          Sprint velocity data (Jira / Linear CSV export)
  - sast_report:         SAST/DAST output (JSON or text)

All cost amounts stored as INTEGER (cents), same as CFO convention.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Shared audit type — reused from CFO pattern
# ---------------------------------------------------------------------------

@dataclass
class CTOStepLog:
    step: str
    ok: bool
    detail: str | None = None
    confidence: float | None = None  # 0–1


# ---------------------------------------------------------------------------
# CTO Run State — threaded through all LangGraph nodes
# ---------------------------------------------------------------------------

class CTOState(TypedDict, total=False):
    # ── Input ─────────────────────────────────────────────────────────────────
    job_id: str
    company_name: str | None

    # Raw input data (at least one required)
    cloud_billing_csv: str | None    # cloud cost export
    git_log_text: str | None         # git log output
    incident_csv: str | None         # incident history
    sprint_csv: str | None           # sprint velocity data
    sast_report: str | None          # security scan output

    # ── InfraAgent ────────────────────────────────────────────────────────────
    infra: dict[str, Any] | None
    # {
    #   total_cost_cents: int,
    #   by_service: {service_name: cost_cents},
    #   by_environment: {prod: X, staging: Y, dev: Z},
    #   top_cost_drivers: [{service, cost, pct, recommendation}],
    #   waste_estimate_cents: int,
    #   waste_items: [{service, reason, savings_cents}],
    #   mom_change_pct: float,
    #   narrative: str,
    #   alerts: [{level, message}]
    # }

    # ── TechDebtAgent ─────────────────────────────────────────────────────────
    tech_debt: dict[str, Any] | None
    # {
    #   total_commits: int,
    #   active_contributors: int,
    #   churn_rate: float,          # % files changed repeatedly
    #   hotspot_files: [{file, changes, authors}],
    #   debt_score: float,           # 0-10 (10 = critical debt)
    #   refactor_priorities: [{area, severity, estimated_days}],
    #   narrative: str
    # }

    # ── IncidentAgent ─────────────────────────────────────────────────────────
    incidents: dict[str, Any] | None
    # {
    #   total_incidents: int,
    #   by_severity: {critical: N, high: N, medium: N, low: N},
    #   mttr_hours: float,            # mean time to recover
    #   mttd_hours: float,            # mean time to detect
    #   sla_breach_count: int,
    #   recurring_services: [{service, count, pct}],
    #   trend: "improving" | "stable" | "degrading",
    #   narrative: str,
    #   alerts: [{level, message}]
    # }

    # ── VelocityAgent ─────────────────────────────────────────────────────────
    velocity: dict[str, Any] | None
    # {
    #   sprints_analyzed: int,
    #   avg_velocity: float,
    #   velocity_trend: "up" | "flat" | "down",
    #   sprint_series: [{sprint, planned, completed, pct}],
    #   predictability_score: float,  # 0-1
    #   bottlenecks: [{area, impact}],
    #   narrative: str
    # }

    # ── SecurityAgent ─────────────────────────────────────────────────────────
    security: dict[str, Any] | None
    # {
    #   critical_vulns: int,
    #   high_vulns: int,
    #   medium_vulns: int,
    #   top_findings: [{cve, severity, component, fix}],
    #   risk_score: float,            # 0-10
    #   narrative: str,
    #   alerts: [{level, message}]
    # }

    # ── CTO Summary ───────────────────────────────────────────────────────────
    cto_summary: dict[str, Any] | None
    # {
    #   overall_health_score: float,  # 0-10
    #   top_risks: [{domain, severity, message}],
    #   quick_wins: [{action, estimated_impact, effort}],
    #   narrative: str
    # }

    # Run control (same as CFO)
    logs: list[CTOStepLog]
    min_confidence: float
    awaiting_review: bool
    halted: bool
    error: str | None


# ---------------------------------------------------------------------------
# Skill result — identical to CFO's SkillResult (reused)
# ---------------------------------------------------------------------------

@dataclass
class CTOSkillResult:
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
class CTORunConfig:
    dry_run: bool = False
    require_review: bool = True
    auto_proceed_min_confidence: float = 0.80


DEFAULT_CTO_RUN_CONFIG = CTORunConfig()


# ---------------------------------------------------------------------------
# Routing constants
# ---------------------------------------------------------------------------

CTO_ROUTE_INFRA    = "infra"
CTO_ROUTE_HOLD     = "hold_for_review"
CTO_ROUTE_END      = "__end__"
CTO_ROUTE_SUMMARY  = "cto_summary"
