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
    # Invoices with a free-form number and no counterparty: they cannot be told from
    # another supplier's same number (plan v10 G23).
    no_counterparty: int = 0
    # Invoices that joined the nearest of too many versions of one number ("çok sayıda sürüm").
    many_versions: int = 0


class OpenItemsOut(BaseModel):
    receivable_cents: int
    payable_cents: int
    no_due_date: int
    other_currency: int


class LedgerMonthOut(BaseModel):
    month: str
    cash_in_cents: int
    cash_out_cents: int


class CurrencySubtotalOut(BaseModel):
    """One non-base currency, summed on its own. Never added to the base figures."""

    currency: str
    revenue_cents: int
    expense_cents: int
    cash_in_cents: int
    cash_out_cents: int
    rows: int
    # Rows whose currency was assumed at upload rather than read (0 until the flag exists).
    assumed_rows: int = 0


class LedgerSummaryOut(BaseModel):
    last_upload: LastUploadOut | None
    open_items: OpenItemsOut
    rows: int
    # The headline currency (`core/currency_totals.effective_base`): the confirmed base currency, or the
    # one currency the data holds while unconfirmed. None when several currencies are present and none
    # is confirmed: then there is no single headline, the headline figures are 0, and `currency_totals`
    # shows every currency side by side.
    currency: str | None
    # confirmed | single_unconfirmed | ambiguous | no_data
    base_state: str
    base_confirmed: bool
    # Where an owner or admin confirms the company currency.
    confirm_path: str
    revenue_cents: int
    expense_cents: int
    # Every currency other than the headline, reported separately and not converted (no rate source).
    other_currencies: list[CurrencySubtotalOut]
    # Every currency, headline included, one entry each.
    currency_totals: list[CurrencySubtotalOut]
    possible_duplicates: int
    period: LedgerPeriodOut
    months: list[LedgerMonthOut]
