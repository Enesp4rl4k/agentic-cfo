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

from app.platform.policies import CONFIDENCE_AUTO_PROCEED_MIN


def is_correction_row(tx: dict[str, Any]) -> bool:
    """A closed-month category correction row (ledger `corrects_id` set).

    It moves an amount between categories; it is not a payment and opens no period.
    Category totals read it, detectors and period lists do not.
    """
    return bool(tx.get("corrects_id"))


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
    # More documents of the same analysis: [{"path": ..., "type": ..., "ad": ...}].
    # Several invoices dropped together are one analysis, not one each.
    ek_belgeler: list[dict[str, str]]

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
    budget_input: dict[str, Any] | None
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
    # The org's standing category corrections (classifier.RuleSpec as dicts),
    # loaded by the caller — nodes hold no DB session. Applied right after
    # ingestion so every downstream figure uses the user's categories.
    category_rules: list[dict[str, Any]] | None
    # {rule_id: matches} from this run; the caller adds them to hit_count.
    category_rule_hits: dict[str, int] | None
    # {profit, cash}: a company analysis reads its ledger instead of a file. Profit
    # and cash are different rows of one money (plan v9 §K1), so cash has its own.
    ledger_view: dict[str, Any] | None
    # The headline currency of this run's figures, and what was left out of them: one sub-total per
    # other currency ({currency, revenue_cents, expense_cents, cash_in_cents, cash_out_cents, rows}).
    # Rows in another currency are removed from `transactions` after ingestion (never added).
    base_currency: str | None
    # confirmed | single_unconfirmed | ambiguous | no_data: how `base_currency` was decided.
    base_state: str | None
    foreign_totals: list[dict[str, Any]] | None
    # The rows `transactions` was cut down without (other currencies): still stored with the job, never summed.
    foreign_transactions: list[dict[str, Any]]
    # Extracted rows waiting for a person (unknown/low confidence, unknown currency):
    # not in `transactions`, so no figure in this run includes them.
    held_transactions: list[dict[str, Any]]
    # What the readers did with every row (app.services.ingest.okuma): read, booked, held, skipped and counted.
    ingest_counts: dict[str, Any]
    # {date, balance_cents} the statement closes on, proven over ALL its rows as read
    # (held ones included, in file order). Set only when rows were held: the balance is
    # a fact of the file, not of which rows a person still has to look at.
    statement_closing_balance: dict[str, Any] | None
    # {date, balance_cents, job_id, filename}: the latest balance the company's completed
    # statements prove (`bank_balance.proven_balance`, the cash radar's own source), loaded by
    # the caller since nodes hold no session. The forecast's runway starts from the newer of
    # this and the balance this run's own statement proves; None → no runway is claimed.
    opening_cash: dict[str, Any] | None
    # {start, end, opening_cents, closing_cents}: the days this run's statement covers, proven
    # over ALL its rows (like `statement_closing_balance`); and, for a company analysis that
    # reads its ledger, the extents of every completed statement (loaded by the caller). They say
    # which calendar months are complete (`app.services.coverage`).
    statement_extent: dict[str, Any] | None
    # {start, end}: the period the file's own header states ("Dönem: 01.01.2026 - 31.03.2026"),
    # when it states one its rows fit in: proof of the days the statement covers.
    statement_period: dict[str, Any] | None
    statement_extents: list[dict[str, Any]] | None
    # Independent verifier output (separate LangGraph step)
    verifier_verdict: dict[str, Any] | None
    # Numeric reconciliation output (separate LangGraph step, runs before verifier)
    reconciliation: dict[str, Any] | None
    # Per-step confidence decomposition (why is min_confidence what it is)
    confidence_breakdown: dict[str, Any] | None


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
    auto_proceed_min_confidence: float = CONFIDENCE_AUTO_PROCEED_MIN


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
