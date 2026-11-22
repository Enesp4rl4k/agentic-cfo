"""Documents held as possible duplicates, as the cash radar reports them: counted, placed, never converted.

A held row opens no open item, so the radar cannot see it; without this entry an unresolved queue
quietly under-counts outflows. Split out of `cash_radar` (which imports it) to keep that module readable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.currency_totals import DEFAULT_BASE, normalise
from app.models.canonical_transaction import CanonicalTransaction, money_rows
from app.services.ledger_documents import (
    DOCUMENT,
    POSSIBLE_DUPLICATE,
    hold_reason,
    load_aliases,
    source_transaction,
)


@dataclass(frozen=True)
class BasisSplit:
    """One side of a week (money in or money out) by how well each part is known."""

    known_cents: int = 0
    estimated_cents: int = 0
    assumed_cents: int = 0


@dataclass(frozen=True)
class HeldWeek:
    week: int
    payable_cents: int
    receivable_cents: int


@dataclass(frozen=True)
class HeldDocuments:
    """Documents waiting for a person's answer (possible duplicates): not in the radar, and said so.

    A held row opens no open item, so the radar cannot see it; without this entry an unresolved queue
    quietly under-counts outflows. Placed as the item would be if kept: on its due date (basis
    `known`), an overdue payable in week 1 (`assumed`, as the radar places it), no date in `undated_*`.
    Foreign currency is counted, never converted.
    """

    count: int
    payable_cents: int
    receivable_cents: int
    weeks: list[HeldWeek]
    payable_basis: BasisSplit
    week1_payable_cents: int
    undated_payable_cents: int
    undated_receivable_cents: int
    beyond_horizon_payable_cents: int
    other_currency_count: int
    other_currency_payable_count: int
    review_path: str = "/onay"  # the screen where a person answers (frontend route)
    # Why they are held: `hold_reason` code -> how many (the words are `HOLD_REASONS_TR`).
    by_reason: dict[str, int] = field(default_factory=dict)


async def held_documents(
    db: AsyncSession, org_id: str, anchor: date, ranges: list[tuple[date, date]], currency: str = DEFAULT_BASE
) -> HeldDocuments | None:
    """Held invoices, by the week they would fall in if kept; None when nothing is held."""
    rows = (await db.execute(
        select(CanonicalTransaction).where(
            CanonicalTransaction.org_id == org_id,
            CanonicalTransaction.ledger_status == POSSIBLE_DUPLICATE,
            CanonicalTransaction.basis == DOCUMENT,
            CanonicalTransaction.amount_cents > 0,
            money_rows(),
        )
    )).scalars().all()
    rows = [r for r in rows if r.source_record_id.startswith(("doc:", "inv:"))]
    if not rows:
        return None
    aliases, cache = await load_aliases(db, org_id), {}
    horizon_end = ranges[-1][1]
    weeks: dict[int, list[int]] = {}
    known = assumed = week1 = undated_pay = undated_rec = beyond = foreign = foreign_pay = pay = rec = 0
    by_reason: dict[str, int] = {}
    for row in rows:
        reason = await hold_reason(db, row, aliases, cache)
        by_reason[reason] = by_reason.get(reason, 0) + 1
        payable = row.direction != "income"
        if normalise(row.currency) != currency:
            foreign += 1
            foreign_pay += int(payable)
            continue
        pay, rec = pay + (row.amount_cents if payable else 0), rec + (0 if payable else row.amount_cents)
        tx = await source_transaction(db, row, aliases, cache)
        due = tx.due_date if tx else None
        if due is None:
            undated_pay += row.amount_cents if payable else 0
            undated_rec += 0 if payable else row.amount_cents
        elif due > horizon_end:
            beyond += row.amount_cents if payable else 0
        else:
            overdue = due < anchor
            index = 0 if overdue else (due - anchor).days // 7
            slot = weeks.setdefault(index, [0, 0])
            slot[0 if payable else 1] += row.amount_cents
            if payable and overdue:
                assumed += row.amount_cents
            elif payable:
                known += row.amount_cents
            week1 += row.amount_cents if payable and index == 0 else 0
    return HeldDocuments(
        count=len(rows), payable_cents=pay, receivable_cents=rec,
        weeks=[HeldWeek(week=i + 1, payable_cents=v[0], receivable_cents=v[1]) for i, v in sorted(weeks.items())],
        payable_basis=BasisSplit(known_cents=known, estimated_cents=0, assumed_cents=assumed),
        week1_payable_cents=week1, undated_payable_cents=undated_pay, undated_receivable_cents=undated_rec,
        beyond_horizon_payable_cents=beyond, other_currency_count=foreign, other_currency_payable_count=foreign_pay,
        by_reason=by_reason,
    )
