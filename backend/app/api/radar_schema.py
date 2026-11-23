"""The cash radar as the API publishes it.

`services.cash_radar` builds frozen dataclasses whose week and shortfall lists
hold plain dicts (`asdict(RadarItem)`, the action dicts), so a schema generated
from them says "a list of anything". These models name what is in the lists.
`tests/test_api_contract.py` checks they carry exactly the dataclasses' fields,
so a field added to the radar cannot be dropped from the response unnoticed.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class RadarItemOut(BaseModel):
    id: str
    counterparty: str | None
    description: str | None
    amount_cents: int
    due_date: str | None
    expected_date: str
    delay_days: int
    is_overdue: bool
    instrument: str = "invoice"
    rescheduled: bool = False
    # known: a document with a due date; estimated: from history; assumed: a placement rule.
    basis: Literal["known", "estimated", "assumed"] = "known"
    basis_reason: str = "document_due_date"
    basis_inputs: dict[str, Any] = {}
    rules_verified: bool | None = None


class BasisSplitOut(BaseModel):
    known_cents: int = 0
    estimated_cents: int = 0
    assumed_cents: int = 0


class BalanceAccountOut(BaseModel):
    """One account's latest proven balance, with its own date: the starting cash is their sum."""

    name: str | None = None
    job_id: str | None = None
    as_of: str
    balance_cents: int
    currency: str
    currency_assumed: bool = False
    basis: Literal["known", "assumed"] = "known"
    basis_note: str | None = None
    statements: int = 1
    behind_days: int = 0
    lagging: bool = False
    identity_uncertain: bool = False
    identity_hint: str | None = None
    gaps: list[str] = []


class OtherCurrencyBalanceOut(BaseModel):
    """A bank balance in a currency other than the radar's: shown with its own total, never converted."""

    currency: str
    balance_cents: int
    as_of: str
    accounts: int


class UnprovenStatementOut(BaseModel):
    """A statement with balances that could not be proven: left out of the starting cash, named with why."""

    job_id: str | None = None
    filename: str | None = None
    reason: str


class AccountSideOut(BaseModel):
    name: str | None = None
    identity_hint: str | None = None  # the account identifier, masked to its last four characters
    as_of: str
    balance_cents: int
    currency: str


class AccountQuestionOut(BaseModel):
    """Two proven statements nothing links or separates: are they one bank account? (answered in /onay)"""

    question: str
    a: AccountSideOut
    b: AccountSideOut
    job_ids_a: list[str]
    job_ids_b: list[str]


class RunwayMonthOut(BaseModel):
    month: str
    net_cents: int


class RunwayOut(BaseModel):
    """The measured runway (`services.runway`), or the reason there is none. No number without a basis."""

    status: str
    message: str
    currency: str | None = None
    opening_cash_cents: int | None = None
    as_of: str | None = None
    age_days: int | None = None
    stale: bool | None = None
    source_filename: str | None = None
    balance_basis: Literal["known", "assumed"] | None = None
    identity_uncertain: bool = False
    identity_note: str | None = None
    accounts: list[BalanceAccountOut] = []
    months_needed: int
    months_used: int
    months: list[RunwayMonthOut] = []
    basis: Literal["known", "assumed"] | None = None
    assumptions: list[dict[str, Any]] = []
    avg_monthly_net_cents: int | None = None
    runway_months: float | None = None
    beyond_horizon: bool = False
    level: Literal["critical", "warning"] | None = None
    # Why the balance is only assumed (one sentence each) and whether the runway is low enough to be said first.
    reasons: list[dict[str, str]] = []
    attention: bool = False
    cash_gone: bool = False
    upload_path: str = "/upload"
    other_currencies: list[OtherCurrencyBalanceOut] = []


class OpeningCashOut(BaseModel):
    balance_cents: int
    as_of: str
    age_days: int
    stale: bool
    stale_after_days: int
    source_job_id: str | None
    source_filename: str | None
    # "assumed" when the proof is thin or the accounts are not certain (`basis_note` says why).
    basis: Literal["known", "assumed"] = "known"
    basis_note: str | None = None
    accounts: list[BalanceAccountOut] = []
    identity_uncertain: bool = False
    identity_note: str | None = None


class RadarWeekOut(BaseModel):
    week: int
    start_date: str
    end_date: str
    inflow_cents: int
    outflow_cents: int
    net_cents: int
    end_balance_cents: int
    receivables: list[RadarItemOut]
    payables: list[RadarItemOut]
    inflow_basis: BasisSplitOut
    outflow_basis: BasisSplitOut


class RadarActionOut(BaseModel):
    type: str
    title: str
    detail: str
    amount_cents: int


class ShortfallOut(BaseModel):
    week: int
    week_start: str
    week_end: str
    shortfall_cents: int
    driver: str
    actions: list[RadarActionOut]


class HeldWeekOut(BaseModel):
    week: int
    payable_cents: int
    receivable_cents: int


class HeldDocumentsOut(BaseModel):
    """Possible duplicates waiting for a person: not in the radar, so they are listed here."""

    count: int
    payable_cents: int
    receivable_cents: int
    weeks: list[HeldWeekOut]
    payable_basis: BasisSplitOut
    week1_payable_cents: int
    undated_payable_cents: int
    undated_receivable_cents: int
    beyond_horizon_payable_cents: int
    other_currency_count: int
    other_currency_payable_count: int
    review_path: str
    # Why they are held: reason code -> count (`HOLD_REASONS_TR` has the words).
    by_reason: dict[str, int]


class AwaitingLineOut(BaseModel):
    count: int
    text: str
    path: str


class AwaitingDecisionOut(BaseModel):
    """Decisions waiting on a person, in the two queues, which stay separate: extracted rows and possible duplicates."""

    rows: AwaitingLineOut | None = None
    documents: AwaitingLineOut | None = None


class OtherCurrencyTotalOut(BaseModel):
    """Open items in a currency other than the radar's: counted with their own totals, never converted."""

    currency: str
    receivable_cents: int
    payable_cents: int
    count: int


class CashRadarOut(BaseModel):
    anchor_date: str
    starting_cash_cents: int | None
    starting_cash_as_of: str | None
    weeks: list[RadarWeekOut]
    shortfall: ShortfallOut | None
    overdue_receivables: list[RadarItemOut]
    overdue_payables_cents: int
    undated_receivables_cents: int
    undated_payables_cents: int
    beyond_horizon_cents: int
    other_currency_items: int
    not_included: list[str]
    recurring_payables_cents: int = 0
    tax_obligations_cents: int = 0
    opening_cash: OpeningCashOut | None = None
    held_documents: HeldDocumentsOut | None = None
    awaiting_decision: AwaitingDecisionOut | None = None
    # The radar's currency (the same effective base as the P&L), how it was decided, and the open items left
    # out because they are in another currency.
    currency: str = "TRY"
    base_state: str = "confirmed"
    other_currency_totals: list[OtherCurrencyTotalOut] = []
    other_currency_balances: list[OtherCurrencyBalanceOut] = []
    unproven_statements: list[UnprovenStatementOut] = []
    account_questions: list[AccountQuestionOut] = []
    runway: RunwayOut | None = None
