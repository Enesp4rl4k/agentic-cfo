"""The running-balance arithmetic of a statement: does the balance agree with the directions read?

Split out of `direction.py` (600-line ceiling). Pure functions, no I/O. The balance is the only evidence in a
file that is arithmetic: a step equals its amount in the direction read, or it does not.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any

INCOME = "income"
EXPENSE = "expense"
BOTH_ORDERS = (False, True)     # oldest-first, newest-first: a free parameter unless the dates decide it


def _flip(direction: str | None) -> str | None:
    return None if direction is None else (EXPENSE if direction == INCOME else INCOME)


@dataclass
class Chain:
    matches: int
    inverted: int
    total: int
    newest_first: bool
    bad: list[int]            # rows of a segment whose balances do not equal their amounts in their directions
    outside: list[int] = field(default_factory=list)   # rows with an amount and no balance that no reconciled segment covers


def _signed(mag: int, direction: str) -> int:
    return mag if direction == INCOME else -mag


def _scan(
    order: list[int], mags: list[int | None], dirs: list[str | None], bals: list[int | None],
) -> tuple[int, int, int, list[int], set[int], int]:
    """Segment verification in one row order: between two consecutive balance rows, the signed amounts of the rows
    after the first up to and including the second must add up to the balance's change. With a balance on every
    row a segment is one row (the usual step); with a balance every third row it is three. A segment that does not
    reconcile may still reconcile WITHOUT its balance-less rows (a footer line between two real rows): then those
    rows are outside the chain and the balance row itself is inside."""
    pos = {i: k for k, i in enumerate(order)}
    anchors = [i for i in order if bals[i] is not None]
    m = inv = total = disc = 0       # disc: reconciling segments whose signed sum is NOT zero (they tell the conventions apart)
    bad: list[int] = []
    inside: set[int] = set()
    for p, q in pairwise(anchors):
        seg = order[pos[p] + 1: pos[q] + 1]
        if any(mags[i] is None or dirs[i] is None for i in seg):
            continue
        delta = (bals[q] or 0) - (bals[p] or 0)
        expected = sum(_signed(mags[i] or 0, dirs[i] or INCOME) for i in seg)
        total += 1
        if delta == expected:
            m += 1
            disc += expected != 0
            inside.update(seg)
        elif len(seg) > 1 and delta == _signed(mags[q] or 0, dirs[q] or INCOME):
            m += 1
            disc += delta != 0
            inside.add(q)
        else:
            bad.extend(i for i in seg if mags[i])
            inv += delta == -expected
    return m, inv, total, bad, inside, disc


def _chain(
    mags: list[int | None], dirs: list[str | None], bals: list[int | None], orders: tuple[bool, ...] = BOTH_ORDERS,
) -> Chain:
    """Compare balance movements with the amounts, in the row order that explains the file best."""
    best = Chain(0, 0, 0, False, [])
    n = len(mags)
    for newest_first in orders:
        order = list(range(n))[::-1] if newest_first else list(range(n))
        m, inv, total, bad, inside, _ = _scan(order, mags, dirs, bals)
        has_chain = sum(1 for b in bals if b is not None) >= 2
        outside = [i for i in range(n) if has_chain and mags[i] and bals[i] is None and i not in inside and i not in bad]
        if m + inv > best.matches + best.inverted or (m + inv == best.matches + best.inverted and m > best.matches):
            best = Chain(m, inv, total, newest_first, bad, outside)
    return best


def verdict(
    mags: list[int | None], dirs: list[str | None], bals: list[int | None], min_steps: int = 1,
    orders: tuple[bool, ...] = BOTH_ORDERS,
) -> str:
    """confirmed | inverted | inconclusive | unverified: does the balance agree with the directions read?
    Fewer than `min_steps` checkable steps is not evidence (text-parsed statements need three)."""
    c = _chain(mags, dirs, bals, orders)
    if c.total < min_steps:
        return "unverified"
    if c.matches / c.total >= 0.9:
        return "confirmed"
    if c.inverted / c.total >= 0.9 and c.matches / c.total < 0.5:
        return "inverted"
    return "inconclusive"


def reconciliation_rate(
    mags: list[int | None], dirs: list[str | None], bals: list[int | None], orders: tuple[bool, ...] = BOTH_ORDERS,
) -> int:
    c = _chain(mags, dirs, bals, orders)
    return round(100 * c.matches / c.total) if c.total else 0


def _from_balance(
    mags: list[int | None], bals: list[int | None], orders: tuple[bool, ...] = BOTH_ORDERS,
) -> list[str | None] | None:
    """Directions read off the balance alone: every step must equal its amount, in exactly one order."""
    scored: list[tuple[int, int, list[str | None]]] = []
    for newest_first in BOTH_ORDERS:
        out: list[str | None] = [None] * len(mags)
        hits = total = 0
        for i in range(1, len(mags)):
            later, earlier = (i, i - 1) if not newest_first else (i - 1, i)
            mag, now, before = mags[later], bals[later], bals[earlier]
            if newest_first not in orders or now is None or before is None or mag is None:
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
    """Rows with an amount and no balance, when the directions come from the balance itself (`_from_balance`: every
    step is adjacent, so a row without a balance is simply not a link). Needs two balances elsewhere."""
    with_balance = sum(1 for i, b in enumerate(bals) if b is not None and i not in skip)
    if with_balance < 2:
        return set()
    return {i for i, (m, b) in enumerate(zip(mags, bals, strict=True)) if m and b is None and i not in skip}


def date_orders(dates: list[str | None]) -> tuple[bool, ...]:
    """The row orders the dates allow: only oldest-first when the dates never go back and do advance, only newest-first
    when they never go forward and do fall; otherwise (ties only, a mix, unreadable) both. The order is evidence the
    file already holds; it must not be a free parameter the arithmetic can use to fit either convention."""
    from app.core.dates import parse_transaction_date

    days = []
    for raw in dates:
        if raw is None or not str(raw).strip():
            continue
        when, estimated = parse_transaction_date(str(raw))
        if not estimated:
            days.append(when)
    if len(days) < 2 or days[0] == days[-1]:
        return BOTH_ORDERS
    if all(a <= b for a, b in pairwise(days)):
        return (False,)
    if all(a >= b for a, b in pairwise(days)):
        return (True,)
    return BOTH_ORDERS


def convention_proof(
    mags: list[int | None], dirs: list[str | None], bals: list[int | None], orders: tuple[bool, ...] = BOTH_ORDERS,
    min_steps: int = 1,
) -> str:
    """Whether the balance chain PROVES the directions read: proven | weak | ambiguous | no.

    A check that passes under both hypotheses is not evidence for either. Both conventions (as read, and flipped) are
    tried in every allowed row order; a convention fits when its segments reconcile (>= 90%). It is proven only if
    exactly the convention as read fits, with at least two DISCRIMINATING segments (reconciling, signed sum not zero).
    One is `weak` (the suggestion, not a proof); none is `no`; if the flipped reading fits as well (zero-sum segments,
    or the two orders disagree) it is `ambiguous`."""
    fits: list[tuple[bool, int]] = []
    for flip in (False, True):
        d = dirs if not flip else [_flip(x) for x in dirs]
        for newest_first in orders:
            order = list(range(len(mags)))[::-1] if newest_first else list(range(len(mags)))
            m, _inv, total, _bad, _inside, disc = _scan(order, mags, d, bals)
            if total and total >= min_steps and m / total >= 0.9:
                fits.append((flip, disc))
    conventions = {flip for flip, _ in fits}
    if conventions == {False, True}:
        return "ambiguous"
    if conventions != {False}:
        return "no"
    disc = max(d for _, d in fits)
    return "proven" if disc >= 2 else "weak" if disc == 1 else "no"
