"""
CMO Agent kernel types — mirrors CTO state pattern, marketing domain.

CMOState is threaded through all CMO LangGraph nodes.

Data inputs (what CMO agents consume):
  - campaign_csv:    Campaign performance data (Google Ads / Meta Ads CSV export)
  - funnel_csv:      Lead funnel data (HubSpot / Salesforce CSV export)
  - cohort_csv:      User cohort retention data (Mixpanel / Amplitude CSV export)

All monetary amounts stored as INTEGER (cents), same as CFO/CTO convention.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Shared audit type
# ---------------------------------------------------------------------------

@dataclass
class CMOStepLog:
    step: str
    ok: bool
    detail: str | None = None
    confidence: float | None = None  # 0–1


# ---------------------------------------------------------------------------
# CMO Run State — threaded through all LangGraph nodes
# ---------------------------------------------------------------------------

class CMOState(TypedDict, total=False):
    # ── Input ─────────────────────────────────────────────────────────────────
    job_id: str
    company_name: str | None
    period: str | None                # e.g. "Q2 2025"

    # Raw input data (at least one required)
    campaign_csv: str | None          # campaign performance export
    funnel_csv: str | None            # lead funnel data
    cohort_csv: str | None            # user retention cohort data

    # ── CampaignAgent ─────────────────────────────────────────────────────────
    campaigns: dict[str, Any] | None
    # {
    #   total_spend_cents: int,
    #   total_revenue_cents: int,
    #   overall_roas: float,           # return on ad spend
    #   overall_cac_cents: int,        # customer acquisition cost
    #   by_channel: {channel: {spend, revenue, roas, cac, conversions}},
    #   top_campaigns: [{name, channel, spend, roas, cac, status}],
    #   underperforming: [{name, channel, spend, roas, reason}],
    #   alerts: [{level, message}],
    #   narrative: str
    # }

    # ── FunnelAgent ───────────────────────────────────────────────────────────
    funnel: dict[str, Any] | None
    # {
    #   total_leads: int,
    #   mql_count: int,
    #   sql_count: int,
    #   won_count: int,
    #   lead_to_mql_rate: float,       # 0-1
    #   mql_to_sql_rate: float,
    #   sql_to_won_rate: float,
    #   overall_conversion_rate: float,
    #   avg_cycle_days: float,
    #   by_source: {source: {leads, mqls, sqls, won, conversion_rate}},
    #   bottleneck_stage: str,         # "lead_to_mql" | "mql_to_sql" | "sql_to_won"
    #   alerts: [{level, message}],
    #   narrative: str
    # }

    # ── CohortAgent ───────────────────────────────────────────────────────────
    cohorts: dict[str, Any] | None
    # {
    #   cohorts_analyzed: int,
    #   avg_retention_30d: float,      # 0-1
    #   avg_retention_90d: float,
    #   avg_ltv_cents: int,
    #   ltv_cac_ratio: float,
    #   best_cohort: {period, retention_30d, ltv},
    #   worst_cohort: {period, retention_30d, ltv},
    #   churn_rate: float,             # monthly avg
    #   retention_trend: "improving" | "stable" | "degrading",
    #   alerts: [{level, message}],
    #   narrative: str
    # }

    # ── CMO Summary ───────────────────────────────────────────────────────────
    cmo_summary: dict[str, Any] | None
    # {
    #   overall_marketing_score: float,  # 0-10
    #   growth_efficiency_score: float,  # 0-10 (LTV:CAC, ROAS)
    #   top_risks: [{domain, severity, message}],
    #   quick_wins: [{action, estimated_impact, effort}],
    #   narrative: str
    # }

    # Run control
    logs: list[CMOStepLog]
    min_confidence: float
    awaiting_review: bool
    halted: bool
    error: str | None


# ---------------------------------------------------------------------------
# Skill result
# ---------------------------------------------------------------------------

@dataclass
class CMOSkillResult:
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
class CMORunConfig:
    dry_run: bool = False
    require_review: bool = True
    auto_proceed_min_confidence: float = 0.80


DEFAULT_CMO_RUN_CONFIG = CMORunConfig()


# ---------------------------------------------------------------------------
# Routing constants
# ---------------------------------------------------------------------------

CMO_ROUTE_CAMPAIGNS = "campaigns"
CMO_ROUTE_HOLD      = "hold_for_review"
CMO_ROUTE_END       = "__end__"
CMO_ROUTE_SUMMARY   = "cmo_summary"
