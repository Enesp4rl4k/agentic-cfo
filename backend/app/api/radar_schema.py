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


class OpeningCashOut(BaseModel):
    balance_cents: int
    as_of: str
    age_days: int
    stale: bool
    stale_after_days: int
    source_job_id: str | None
    source_filename: str | None


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
    # The radar's currency (the same effective base as the P&L), how it was decided, and the open items left
    # out because they are in another currency.
    currency: str = "TRY"
    base_state: str = "confirmed"
    other_currency_totals: list[OtherCurrencyTotalOut] = []
