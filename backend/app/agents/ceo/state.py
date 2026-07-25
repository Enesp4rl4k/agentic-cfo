"""
CEO Agent kernel types.

CEO is the meta-orchestrator: it runs CFO + CTO pipelines in parallel,
then synthesizes their outputs into cross-domain insights.

CEO's unique value:
  CFO says "cash runway 4 months"
  CTO says "infra costs 40% above benchmark"
  CEO synthesizes: "optimize infra → save $X → extend runway by 2 months"

CEOState carries:
  - financial_summary: condensed CFO pipeline output
  - tech_summary:      condensed CTO pipeline output
  - cross_risks:       correlated risks across domains
  - strategic_priorities: ranked action list
  - board_deck:        executive presentation data
  - okr_status:        OKR tracking (optional)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TypedDict


@dataclass
class CEOStepLog:
    step: str
    ok: bool
    detail: str | None = None
    confidence: float | None = None


class CEOState(TypedDict, total=False):
    # ── Input ─────────────────────────────────────────────────────────────────
    job_id: str
    company_name: str | None
    period: str | None            # e.g. "2024-Q1", "2024-06"

    # ── CFO pipeline output (condensed) ───────────────────────────────────────
    financial_summary: dict[str, Any] | None
    # {
    #   revenue_cents, net_income_cents, net_margin,
    #   cash_runway_months, cash_flow_net_cents,
    #   forecast_base_12m_cents, top_alerts: [{level, message}],
    #   narrative: str
    # }

    # ── CTO pipeline output (condensed) ───────────────────────────────────────
    tech_summary: dict[str, Any] | None
    # {
    #   overall_health_score,
    #   infra_cost_cents, infra_waste_cents,
    #   debt_score, mttr_hours, avg_velocity,
    #   top_risks: [{domain, severity, message}],
    #   narrative: str
    # }

    # ── CMO pipeline output (condensed) ───────────────────────────────────────
    marketing_summary: dict[str, Any] | None
    # {
    #   overall_marketing_score: float,  # 0-10
    #   overall_roas: float,
    #   overall_cac_cents: int,
    #   ltv_cac_ratio: float,
    #   churn_rate: float,
    #   overall_conversion_rate: float,
    #   top_risks: [{domain, severity, message}],
    #   narrative: str
    # }

    # ── Compliance pipeline output (condensed) ────────────────────────────────
    compliance_summary: dict[str, Any] | None
    # {
    #   overall_health_score: float,   # 0-100
    #   health_status: str,            # excellent|good|fair|poor|critical
    #   critical_open_violations: int,
    #   open_violations: int,
    #   overdue_violations: int,
    #   remediation_rate: float,
    #   compliance_coverage_pct: float,
    #   non_compliant_requirements: int,
    #   frameworks: [str],
    #   active_policies: int,
    #   top_risks: [{domain, severity, message}],
    #   narrative: str
    # }

    # ── COO pipeline output (condensed) ───────────────────────────────────────
    ops_summary: dict[str, Any] | None
    # {
    #   overall_ops_score: float,          # 0-10 (lower = worse)
    #   operational_efficiency_score: float,  # 0-10 (higher = better)
    #   sla_breach_rate: float,
    #   avg_utilization_rate: float,
    #   process_efficiency_score: float,
    #   top_risks: [{domain, severity, message}],
    #   narrative: str
    # }

    # ── Cross-domain synthesis ────────────────────────────────────────────────
    cross_risks: list[dict[str, Any]]
    # [{
    #   risk_id, title, domains: [cfo|cto],
    #   severity, financial_impact_cents,
    #   tech_impact, recommended_action, urgency: now|30d|90d
    # }]

    # ── Strategic priorities ──────────────────────────────────────────────────
    strategic_priorities: list[dict[str, Any]]
    # [{
    #   rank, title, rationale,
    #   expected_outcome, timeline_weeks,
    #   owner_role: CEO|CFO|CTO|Engineering|Finance,
    #   effort: low|medium|high,
    #   impact: low|medium|high|critical
    # }]

    # ── Board deck ────────────────────────────────────────────────────────────
    board_deck: dict[str, Any] | None
    # {
    #   title, period, executive_summary,
    #   slides: [
    #     {slide_number, title, key_metrics: [...], narrative, chart_type}
    #   ],
    #   one_page_summary: str  (plain text, printable)
    # }

    # ── OKR tracking ─────────────────────────────────────────────────────────
    okr_status: dict[str, Any] | None
    # {
    #   objectives: [{title, key_results: [{kr, target, actual, status}]}]
    # }

    # Run control
    logs: list[CEOStepLog]
    min_confidence: float
    awaiting_review: bool
    halted: bool
    error: str | None


@dataclass
class CEOSkillResult:
    ok: bool
    patch: dict[str, Any] = field(default_factory=dict)
    confidence: float | None = None
    needs_review: bool = False
    detail: str | None = None


@dataclass
class CEORunConfig:
    dry_run: bool = False
    require_review: bool = False   # CEO is exec-level, auto-proceed by default
    auto_proceed_min_confidence: float = 0.75


DEFAULT_CEO_RUN_CONFIG = CEORunConfig()

# Routing constants
CEO_ROUTE_SYNTHESIS   = "synthesis"
CEO_ROUTE_PRIORITIES  = "strategic_priorities"
CEO_ROUTE_BOARD_DECK  = "board_deck"
CEO_ROUTE_HOLD        = "hold_for_review"
CEO_ROUTE_END         = "__end__"
