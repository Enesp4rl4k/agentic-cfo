"""Bank reconciliation: a bank movement settles the invoice it pays.

An invoice is revenue when issued; its bank receipt is that money arriving weeks
later. With both in the ledger, the same sale counted twice (plan v9 §K1). Here a
movement is matched to the open item it pays, which closes the item and takes the
line out of profit (it stays in cash).

Automatic only where a person would not hesitate:

- the invoice number is in the description and the amount is exact;
- the counterparty's name is in the description, the amount is exact, and only one
  open item fits.

A lump (one transfer paying several invoices of one customer) is never automatic:
see `_decide_lump`.

Everything else that could be the same money is a *proposal*: the amount alone,
several invoices that fit, part of an invoice. A proposal holds the line out of
profit until a person answers, and a "no" is remembered. A movement that fits
nothing stays what it was: its own money.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.turkish import fold
from app.models.canonical_transaction import CanonicalTransaction
from app.models.open_item import OpenItem
from app.models.open_item_match import OpenItemMatch

CASH = "cash"
CONFIRMED = "confirmed"
PROPOSED = "proposed"
REJECTED = "rejected"

BY_NUMBER = "invoice_number"
BY_NAME = "counterparty_and_amount"
BY_AMOUNT = "amount_only"
BY_SUM = "sum_of_open_items"

# A lump is searched among one customer's open items; past this many the search is
# both slow and too likely to find a coincidence, so no guess is made.
_MAX_LUMP_CANDIDATES = 15

# A payment a few days before the invoice's date happens; months before does not.
_EARLIEST = timedelta(days=3)
# Words that say nothing about who a company is.
_NOISE = frozenset({
    "as", "ltd", "sti", "san", "tic", "ve", "a", "s", "anonim", "limited", "sirketi", "sirket",
    "sanayi", "ticaret", "holding", "group", "grup", "insaat", "hizmetleri", "bilgi",
})
_INVOICE_NUMBER = re.compile(r"e-Fatura ([^:]+):")


def _words(text: str | None) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", fold(text)) if len(w) > 1}


def _name_in(counterparty: str | None, description: str | None) -> bool:
    """Every telling word of the counterparty's name is in the description."""
    name = _words(counterparty) - _NOISE
    return bool(name) and name <= _words(description)


def _number_in(item: OpenItem, description: str | None) -> bool:
    found = _INVOICE_NUMBER.search(item.description or "")
    return bool(found) and fold(found.group(1)).strip() in fold(description)


def _day(when: datetime) -> date:
    return when.astimezone(UTC).date() if when.tzinfo else when.date()


def _remaining(item: OpenItem) -> int:
    return item.amount_cents - item.paid_cents


@dataclass(frozen=True)
class _Match:
    item: OpenItem
    amount: int
    method: str
    status: str


def _decide(row: CanonicalTransaction, items: list[OpenItem], refused: set[str]) -> _Match | None:
    """What this movement is to these open items, if anything."""
    day = _day(row.transaction_date)
    fits = [
        i for i in items
        if i.currency == row.currency and i.id not in refused and _remaining(i) > 0
        and i.direction == ("receivable" if row.direction == "income" else "payable")
        and day >= i.issue_date - _EARLIEST
    ]
    exact = [i for i in fits if _remaining(i) == row.amount_cents]

    quoted = [i for i in fits if _number_in(i, row.description)]
    if quoted:
        item = quoted[0]
        if _remaining(item) == row.amount_cents:
            return _Match(item, row.amount_cents, BY_NUMBER, CONFIRMED)
        if row.amount_cents < _remaining(item):
            return _Match(item, row.amount_cents, BY_NUMBER, PROPOSED)
        return None

    named = [i for i in exact if _name_in(i.counterparty, row.description)]
    if len(named) == 1:
        return _Match(named[0], row.amount_cents, BY_NAME, CONFIRMED)
    if named:
        return _Match(_soonest(named), row.amount_cents, BY_NAME, PROPOSED)
    if exact:
        return _Match(_soonest(exact), row.amount_cents, BY_AMOUNT, PROPOSED)
    return None


def _decide_lump(
    row: CanonicalTransaction, items: list[OpenItem], refused: set[str], reserved: set[str]
) -> list[_Match]:
    """Several open items of one counterparty that together are exactly this movement.

    Always a proposal, and only when nothing is left to guess: the counterparty's
    name is in the description, every item is named and not already waiting on an
    answer, and exactly one combination adds up. A near miss, two combinations
    with the same total, or items of different customers give no proposal.
    """
    day = _day(row.transaction_date)
    direction = "receivable" if row.direction == "income" else "payable"
    by_party: dict[str, list[OpenItem]] = {}
    for i in items:
        if (
            i.currency == row.currency and i.id not in refused and i.id not in reserved
            and _remaining(i) > 0 and i.direction == direction and i.counterparty
            and day >= i.issue_date - _EARLIEST
            and _name_in(i.counterparty, row.description)
        ):
            by_party.setdefault(fold(i.counterparty), []).append(i)

    found: list[list[OpenItem]] = []
    for group in by_party.values():
        if len(group) < 2 or len(group) > _MAX_LUMP_CANDIDATES:
            continue
        found.extend(_subsets_totalling(group, row.amount_cents))
    if len(found) != 1:
        return []
    return [_Match(i, _remaining(i), BY_SUM, PROPOSED) for i in found[0]]


def _subsets_totalling(group: list[OpenItem], target: int) -> list[list[OpenItem]]:
    """Every combination of two or more items whose remaining amounts add to target."""
    out: list[list[OpenItem]] = []

    def walk(start: int, chosen: list[OpenItem], total: int) -> None:
        if total == target and len(chosen) >= 2:
            out.append(list(chosen))
        if total >= target:
            return
        for k in range(start, len(group)):
            chosen.append(group[k])
            walk(k + 1, chosen, total + _remaining(group[k]))
            chosen.pop()

    walk(0, [], 0)
    return out


def _soonest(items: list[OpenItem]) -> OpenItem:
    return min(items, key=lambda i: (i.due_date or date.max, i.issue_date))


def apply_payment(item: OpenItem, amount: int) -> None:
    item.paid_cents += amount
    if item.paid_cents >= item.amount_cents:
        item.status = "settled"


async def reconcile_org(db: AsyncSession, org_id: str) -> dict[str, int]:
    """Match unmatched bank movements to open items. Idempotent; does not commit."""
    counts = {"settled": 0, "proposed": 0}
    items = list((await db.execute(
        select(OpenItem).where(OpenItem.org_id == org_id, OpenItem.status == "open")
    )).scalars())
    if not items:
        return counts

    matches = (await db.execute(
        select(OpenItemMatch.ledger_row_id, OpenItemMatch.open_item_id, OpenItemMatch.status)
        .where(OpenItemMatch.org_id == org_id)
    )).all()
    taken = {m.ledger_row_id for m in matches if m.status != REJECTED}
    reserved = {m.open_item_id for m in matches if m.status == PROPOSED}
    refused: dict[str, set[str]] = {}
    for m in matches:
        if m.status == REJECTED:
            refused.setdefault(m.ledger_row_id, set()).add(m.open_item_id)

    rows = (await db.execute(
        select(CanonicalTransaction)
        .where(
            CanonicalTransaction.org_id == org_id,
            CanonicalTransaction.basis == CASH,
            CanonicalTransaction.ledger_status == "active",
            CanonicalTransaction.amount_cents > 0,
        )
        .order_by(CanonicalTransaction.transaction_date)
    )).scalars().all()

    for row in rows:
        if row.id in taken:
            continue
        match = _decide(row, items, refused.get(row.id, set()))
        if match is None:
            lump = _decide_lump(row, items, refused.get(row.id, set()), reserved)
            for part in lump:
                db.add(OpenItemMatch(
                    org_id=org_id, open_item_id=part.item.id, ledger_row_id=row.id,
                    amount_cents=part.amount, method=part.method, status=part.status,
                    matched_on=_day(row.transaction_date),
                ))
                reserved.add(part.item.id)
            if lump:
                counts["proposed"] += 1
            continue
        db.add(OpenItemMatch(
            org_id=org_id, open_item_id=match.item.id, ledger_row_id=row.id,
            amount_cents=match.amount, method=match.method, status=match.status,
            matched_on=_day(row.transaction_date),
        ))
        if match.status == CONFIRMED:
            apply_payment(match.item, match.amount)
            counts["settled"] += 1
        else:
            counts["proposed"] += 1
    await db.flush()
    return counts


async def rows_settling_items(db: AsyncSession, org_id: str) -> set[str]:
    """Ledger rows that pay an invoice, or may: cash, not profit."""
    return set((await db.execute(
        select(OpenItemMatch.ledger_row_id).where(
            OpenItemMatch.org_id == org_id,
            OpenItemMatch.status.in_((CONFIRMED, PROPOSED)),
        )
    )).scalars())


async def payment_behaviour(db: AsyncSession, org_id: str) -> list[dict[str, Any]]:
    """How late each counterparty really settles, from confirmed matches.

    Only full settlements with a due date: a part-payment says little about when
    the bill was paid, and an undated invoice was never late.
    """
    rows = await db.execute(
        select(OpenItem.counterparty, OpenItem.direction, OpenItem.due_date, OpenItemMatch.matched_on)
        .join(OpenItemMatch, OpenItemMatch.open_item_id == OpenItem.id)
        .where(
            OpenItem.org_id == org_id,
            OpenItem.status == "settled",
            OpenItem.due_date.is_not(None),
            OpenItemMatch.status == CONFIRMED,
        )
    )
    delays: dict[tuple[str, str], list[int]] = {}
    for counterparty, direction, due, paid in rows:
        delays.setdefault((counterparty or "", direction), []).append((paid - due).days)
    return [
        {"counterparty": name, "direction": direction, "settled": len(days),
         "average_delay_days": round(sum(days) / len(days), 1)}
        for (name, direction), days in sorted(delays.items())
    ]
