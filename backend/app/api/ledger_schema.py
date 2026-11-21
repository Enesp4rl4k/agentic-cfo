"""The company-ledger summary, typed: its figures and the period they were read for."""
from __future__ import annotations

from pydantic import BaseModel


class LedgerPeriodOut(BaseModel):
    start: str | None
    end: str | None
    months: int
    label: str | None
    is_default: bool
    available_start: str | None
    available_end: str | None
    available_months: int
    future_rows: int
    future_latest: str | None


class LastUploadOut(BaseModel):
    filename: str | None = None
    new: int = 0
    already: int = 0
    possible_duplicate: int = 0
    no_date: int = 0
    settled: int = 0
    proposed: int = 0


class OpenItemsOut(BaseModel):
    receivable_cents: int
    payable_cents: int
    no_due_date: int
    other_currency: int


class LedgerMonthOut(BaseModel):
    month: str
    cash_in_cents: int
    cash_out_cents: int


class LedgerSummaryOut(BaseModel):
    last_upload: LastUploadOut | None
    open_items: OpenItemsOut
    rows: int
    revenue_cents: int
    expense_cents: int
    possible_duplicates: int
    period: LedgerPeriodOut
    months: list[LedgerMonthOut]
