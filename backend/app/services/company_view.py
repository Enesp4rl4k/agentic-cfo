"""Which figures are "the company's picture" (plan v7 §P0 / W2, plan v9 §K1).

Every completed CFO analysis used to become the company's active analysis —
the context the CEO synthesis, the semantic snapshot, the command center and
the triggers read. Live audit 2026-10-24: approving a broken CSV made it the
active analysis and the company snapshot lost revenue, runway and margin; a
twelve-month view was replaced by one file.

The picture is now read from the company's ledger: `ledger_view` hands the CFO
pipeline every counted row instead of a file, so one invoice adds one invoice.

`should_replace` is what is left of the temporary rule: it decides only when the
ledger holds nothing to read (no dated row at all). A new analysis then replaces
the current one when it adds a period: it covers at least as many months, or it
reaches a later month. The person can still apply an analysis explicitly
(POST /analysis/{id}/company-view); the next upload or decision supersedes it.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.currency_totals import foreign_summaries, split_by_currency
from app.services.ledger import Period, company_rows, day_of

_MONTH = re.compile(r"^\d{4}-\d{2}$")


@dataclass(frozen=True)
class LedgerView:
    """The rows a company analysis reads, and a fingerprint of what they say."""

    profit: list[dict[str, Any]]
    cash: list[dict[str, Any]]
    period: dict[str, Any]
    signature: str
    # The pipeline reads base-currency rows only: `profit` and `cash` hold no other currency, so
    # no sum, ranking or ratio downstream can mix them. What was left out is `foreign`: one
    # sub-total per other currency, reported beside the base figures and never added to them.
    base_currency: str = "TRY"
    foreign: list[dict[str, Any]] | None = None
    # How `base_currency` was decided (`core/currency_totals.effective_base`): confirmed, single_unconfirmed,
    # or ambiguous (the dominant currency by row count, labelled as such: no single headline exists).
    base_state: str = "confirmed"

    def for_pipeline(self) -> dict[str, Any]:
        return {
            "profit": self.profit, "cash": self.cash,
            "base_currency": self.base_currency, "foreign": self.foreign or [],
            "base_state": self.base_state,
        }


def _as_transaction(row: Any, reclass_of_period: str | None = None) -> dict[str, Any]:
    """A ledger row in the shape the pipeline's own ingestion produces."""
    return {
        "amount_cents": row.amount_cents,
        "currency": row.currency,
        "type": row.direction,
        "category": row.category,
        "account_code": row.account_code,
        "description": row.description,
        "vendor": row.counterparty,
        "transaction_date": day_of(row.transaction_date).isoformat(),
        "ledger_basis": row.basis,
        # Set on a closed-month correction row: category totals read it, detectors do not.
        "corrects_id": row.corrects_id,
        # A correction row whose original sits in a period outside the view's: it moves an
        # amount out of that period's category, so it is not a bare negative.
        "reclass_of_period": reclass_of_period,
    }


def _signature(profit: list[Any], cash: list[Any], foreign: list[dict[str, Any]] | None = None) -> str:
    """What the figures say, not which row ids say it.

    A row's id is random, so a ledger rebuilt from the same uploads has other ids and
    the same money; the signature uses the row's content identity (`source_record_id`,
    which is the document id or the content fingerprint) and sorts, so neither a
    rebuild nor the order rows are read in moves it.
    """
    said: list[Any] = [
        sorted(
            [r.source_record_id, day_of(r.transaction_date).isoformat(), r.amount_cents, r.direction, r.category]
            for r in rows
        )
        for rows in (profit, cash)
    ]
    if foreign:  # other currencies move the picture too, even though they are not in its totals
        said.append(foreign)
    return hashlib.sha256(json.dumps(said).encode()).hexdigest()


async def ledger_view(db: AsyncSession, org_id: str, period: Period | None = None) -> LedgerView | None:
    """What the ledger says about this company in a period (default: the last 12 months
    of data, plan v10 S1.4); None when it says nothing there."""
    rows = await company_rows(db, org_id, period)
    if not rows.profit and not rows.cash:
        return None
    base = rows.base_currency
    profit, _ = split_by_currency(rows.profit, base)
    cash, _ = split_by_currency(rows.cash, base)
    foreign = foreign_summaries(rows.profit, rows.cash, base)
    return LedgerView(
        profit=[_as_transaction(r, rows.reclass_of_period.get(r.id)) for r in profit],
        cash=[_as_transaction(r) for r in cash],
        period=rows.period.as_dict(),
        signature=_signature(profit, cash, foreign),
        base_currency=base,
        foreign=foreign,
        base_state=rows.effective.state,
    )


def months_of(dashboard: dict[str, Any] | None) -> list[str]:
    """Sorted distinct "YYYY-MM" months the dashboard's cash-flow series covers."""
    series = ((dashboard or {}).get("cashflow") or {}).get("monthly_series") or []
    months = {
        str(m.get("month"))
        for m in series
        if isinstance(m, dict) and _MONTH.match(str(m.get("month") or ""))
    }
    return sorted(months)


def should_replace(
    current: dict[str, Any] | None, new: dict[str, Any] | None
) -> tuple[bool, str]:
    """(replace?, reason) for making `new` the company's active analysis."""
    if not new:
        return False, "no_dashboard"
    current_months = months_of(current)
    if not current_months:
        return True, "no_current_view"
    new_months = months_of(new)
    if not new_months:
        return False, "period_unreadable"
    if set(new_months) <= set(current_months) and len(new_months) < len(current_months):
        return False, "narrower_period_within_current_view"
    # Fewer months and nothing newer: a single invoice from an older month must
    # not replace a twelve-month view (seen live with a UBL-TR sample invoice).
    if len(new_months) < len(current_months) and new_months[-1] <= current_months[-1]:
        return False, "narrower_and_not_newer"
    return True, "adds_a_period"
