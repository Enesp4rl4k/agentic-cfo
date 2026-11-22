"""A statement that prints its balance only on some rows, proven segment by segment.

Many exports (and daily-balance PDFs) carry "bakiye" on the last row of each day, not on every row. The balance
between two printed balances must equal the signed amounts of the rows after the first one, up to and including the
second: a "segment". A statement is proven to its closing balance when every segment from the first to the last
printed balance reconciles, in exactly one row order, and at least two segments tell the sign convention apart
(a segment that sums to zero reconciles under either convention and proves nothing about it).

Rows before the first and after the last printed balance (and a footer line between two real rows) are outside the
chain: nothing checks them, they stay held, and the statement is `assumed` with that said, never `known`.
Pure functions, no I/O. The all-rows case stays in `bank_balance._chain_order`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any

from app.parsers.balance_chain import BOTH_ORDERS, date_orders

INCOME = "income"
EXPENSE = "expense"


def placed(row: dict[str, Any]) -> bool:
    return row.get("type") in (INCOME, EXPENSE)


def signed(row: dict[str, Any]) -> int:
    amount = int(row.get("amount_cents") or 0)
    return amount if row.get("type") == INCOME else -amount if row.get("type") == EXPENSE else 0


def _money(row: dict[str, Any]) -> bool:
    return bool(row.get("amount_cents"))


def _unplaced(row: dict[str, Any]) -> bool:
    return _money(row) and not placed(row)


@dataclass
class SegmentChain:
    ordered: list[dict[str, Any]] = field(default_factory=list)   # oldest first, first printed balance .. last
    anchors: list[dict[str, Any]] = field(default_factory=list)   # the rows that print a balance, oldest first
    segments: int = 0
    discriminating: int = 0           # reconciling segments whose signed sum is not zero
    outside: int = 0                  # rows with money that no segment covers (held)
    before_first: bool = False        # a money row precedes the first printed balance: the opening balance is unknown
    reason: str | None = None         # why it does not reconcile; None = it does


def _walk(order: list[dict[str, Any]]) -> tuple[int, int, set[int], str | None]:
    """(segments, discriminating, indexes inside the chain, reason it fails) in one row order."""
    idx = [i for i, r in enumerate(order) if r.get("balance_cents") is not None]
    inside: set[int] = set()
    disc = 0
    for p, q in pairwise(idx):
        seg = order[p + 1: q + 1]
        delta = int(order[q]["balance_cents"]) - int(order[p]["balance_cents"])
        if not _unplaced(seg[-1]) and delta == sum(signed(r) for r in seg):
            # A row whose direction nobody placed adds nothing here: if the rest reconcile it is not part of the
            # balance (a footer line), so it is outside the chain, never inside it.
            inside.update(p + 1 + k for k, r in enumerate(seg) if not _unplaced(r))
        elif len(seg) > 1 and not _unplaced(seg[-1]) and delta == signed(seg[-1]):
            inside.add(q)             # the rows between are not part of the balance (a footer line): outside the chain
        else:
            held = any(_unplaced(r) for r in seg)
            return len(idx) - 1, disc, inside, (
                "zincirin içinde yönü belli olmayan satır var" if held else "bakiye aralıkları satır tutarlarıyla uyuşmuyor")
        disc += delta != 0
    return len(idx) - 1, disc, inside, None


def segment_chain(rows: list[dict[str, Any]]) -> SegmentChain | None:
    """The statement's segment chain, or None when the idea does not apply (every row prints a balance,
    fewer than two do, or a row has no date). `reason` is set when the segments do not reconcile."""
    rows = list(rows)
    carry = [r for r in rows if r.get("balance_cents") is not None]
    if len(carry) < 2 or len(carry) == len(rows) or any(not r.get("transaction_date") for r in rows):
        return None
    allowed = date_orders([str(r["transaction_date"]) for r in rows])
    fits: list[tuple[list[dict[str, Any]], int, int, set[int]]] = []
    failure = "bakiye aralıkları satır tutarlarıyla uyuşmuyor"
    for newest_first in BOTH_ORDERS:
        if newest_first not in allowed:
            continue
        order = rows[::-1] if newest_first else rows
        n, disc, inside, why = _walk(order)
        if why is None:
            fits.append((order, n, disc, inside))
        else:
            failure = why
    if not fits:
        return SegmentChain(reason=failure)
    if len(fits) > 1:
        return SegmentChain(reason="bakiye zinciri her iki sıralamada da tutuyor; hangisinin son olduğu belli değil")
    order, n, disc, inside = fits[0]
    days = [str(r["transaction_date"])[:10] for r in order]
    if days != sorted(days):
        return SegmentChain(reason="bakiye zinciri satır tarihleriyle çelişiyor")
    idx = [i for i, r in enumerate(order) if r.get("balance_cents") is not None]
    outside = sum(1 for i, r in enumerate(order) if _money(r) and r.get("balance_cents") is None and i not in inside)
    return SegmentChain(
        ordered=order[idx[0]: idx[-1] + 1], anchors=[order[i] for i in idx], segments=n, discriminating=disc,
        outside=outside, before_first=any(_money(r) for r in order[: idx[0]]),
    )
