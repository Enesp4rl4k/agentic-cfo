"""The running-balance arithmetic of a statement: does the balance agree with the directions read?

Split out of `direction.py` (600-line ceiling). Pure functions, no I/O. The balance is the only evidence in a
file that is arithmetic: a step equals its amount in the direction read, or it does not.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

INCOME = "income"
EXPENSE = "expense"


def _flip(direction: str | None) -> str | None:
    return None if direction is None else (EXPENSE if direction == INCOME else INCOME)


@dataclass
class Chain:
    matches: int
    inverted: int
    total: int
    newest_first: bool
    bad: list[int]            # rows whose own balance step does not equal their amount in their direction


def _chain(mags: list[int | None], dirs: list[str | None], bals: list[int | None]) -> Chain:
    """Compare balance movements with the amounts, in the row order that explains the file best."""
    best = Chain(0, 0, 0, False, [])
    for newest_first in (False, True):
        m = inv = total = 0
        bad: list[int] = []
        for i in range(1, len(mags)):
            later, earlier = (i, i - 1) if not newest_first else (i - 1, i)
            mag, now, before = mags[later], bals[later], bals[earlier]
            if now is None or before is None or mag is None or dirs[later] is None:
                continue
            delta = now - before
            expected = mag if dirs[later] == INCOME else -mag
            total += 1
            if delta == expected:
                m += 1
            else:
                bad.append(later)
                inv += delta == -expected
        if m + inv > best.matches + best.inverted or (m + inv == best.matches + best.inverted and m > best.matches):
            best = Chain(m, inv, total, newest_first, bad)
    return best


def verdict(
    mags: list[int | None], dirs: list[str | None], bals: list[int | None], min_steps: int = 1,
) -> str:
    """confirmed | inverted | inconclusive | unverified: does the balance agree with the directions read?
    Fewer than `min_steps` checkable steps is not evidence (text-parsed statements need three)."""
    c = _chain(mags, dirs, bals)
    if c.total < min_steps:
        return "unverified"
    if c.matches / c.total >= 0.9:
        return "confirmed"
    if c.inverted / c.total >= 0.9 and c.matches / c.total < 0.5:
        return "inverted"
    return "inconclusive"


def reconciliation_rate(mags: list[int | None], dirs: list[str | None], bals: list[int | None]) -> int:
    c = _chain(mags, dirs, bals)
    return round(100 * c.matches / c.total) if c.total else 0


def _from_balance(mags: list[int | None], bals: list[int | None]) -> list[str | None] | None:
    """Directions read off the balance alone: every step must equal its amount, in exactly one order."""
    scored: list[tuple[int, int, list[str | None]]] = []
    for newest_first in (False, True):
        out: list[str | None] = [None] * len(mags)
        hits = total = 0
        for i in range(1, len(mags)):
            later, earlier = (i, i - 1) if not newest_first else (i - 1, i)
            mag, now, before = mags[later], bals[later], bals[earlier]
            if now is None or before is None or mag is None:
                continue
            delta = now - before
            total += 1
            if mag and abs(delta) == mag:
                hits += 1
                out[later] = INCOME if delta > 0 else EXPENSE
        scored.append((hits, total, out))
    (h0, t0, o0), (h1, t1, o1) = scored
    best_hits, best_total, best = (h0, t0, o0) if h0 >= h1 else (h1, t1, o1)
    other = min(h0, h1)
    if best_total >= 2 and best_hits / best_total >= 0.9 and best_hits > other:
        return best
    return None


def sign_preview(mags: list[int | None], negative: list[bool], sign_rows: list[int]) -> dict[str, Any]:
    """What the sign question shows: a few rows (always one of the rarer sign, when there is one) and the totals of
    both readings, so the person sees what each answer would book."""
    plus = sum(mags[i] or 0 for i in sign_rows if not negative[i])
    minus = sum(mags[i] or 0 for i in sign_rows if negative[i])
    picked = sign_rows[:3]
    rare = [i for i in sign_rows if negative[i] != negative[sign_rows[0]]]
    if rare and rare[0] not in picked:
        picked = [*picked[:2], rare[0]]
    return {
        "sample_rows": picked,
        "totals": {"as_read": {"income": plus, "expense": minus}, "inverted": {"income": minus, "expense": plus}},
        "negative_rows": sum(negative[i] for i in sign_rows), "rows": len(sign_rows),
        # One sign only: nothing in the file could contradict a remembered convention, so a memory never answers for it.
        "uniform": len({negative[i] for i in sign_rows}) == 1,
    }


def outside_chain(mags: list[int | None], bals: list[int | None], skip: frozenset[int] = frozenset()) -> set[int]:
    """Rows with an amount and NO balance inside a statement whose other rows have balances.

    Such a row is not a link of the chain: nothing checks it (a footer-like line with a date and an amount is
    indistinguishable from a transaction). Needs at least two balances elsewhere, or there is no chain at all."""
    with_balance = sum(1 for i, b in enumerate(bals) if b is not None and i not in skip)
    if with_balance < 2:
        return set()
    return {i for i, (m, b) in enumerate(zip(mags, bals, strict=True)) if m and b is None and i not in skip}
