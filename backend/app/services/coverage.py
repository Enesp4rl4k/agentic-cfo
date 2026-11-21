"""Which calendar months a company's cash rows cover completely.

A month with rows is not a month of data: a statement that starts on the 7th, or ends on the
5th, shows part of that month. Treating it as a whole month understates the burn (the error is
always optimistic) and a skipped month is not "the previous one". So a month is COMPLETE only
when the data's proven extent spans it from its first day to its last:

- the extent of a statement is its first and last transaction date (no bank file here states its
  period). A statement whose balances chain proves nothing is missing inside that extent;
- two statements are one account's consecutive statements when the first closes on the balance
  the second opens on (`bank_balance.statement_extent`): their extents join;
- statements that do not join are different accounts (or unproven), and a month is complete only
  when EVERY such group covers it: another bank's missing months are unknown, not zero.

A month inside the coverage with no rows is a real zero month; one outside it is missing.
"""
from __future__ import annotations

import calendar
from datetime import date
from typing import Any

from app.services.bank_balance import statement_extent


def _day(value: Any) -> date:
    return date.fromisoformat(str(value)[:10])


def month_bounds(month: str) -> tuple[date, date]:
    y, m = int(month[:4]), int(month[5:7])
    return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])


def month_range(first: str, last: str) -> list[str]:
    """Every "YYYY-MM" from `first` to `last`, both included."""
    out: list[str] = []
    y, m = int(first[:4]), int(first[5:7])
    while f"{y:04d}-{m:02d}" <= last:
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def next_month(month: str) -> str:
    y, m = int(month[:4]), int(month[5:7])
    return f"{y + 1:04d}-01" if m == 12 else f"{y:04d}-{m + 1:02d}"


def extent_of_rows(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """First and last transaction date of the rows, with no balance proof."""
    dates = sorted(str(r["transaction_date"])[:10] for r in rows if r.get("transaction_date"))
    return {"start": dates[0], "end": dates[-1]} if dates else None


def extents_for(state: dict[str, Any]) -> list[dict[str, Any]]:
    """The extents that say which months of THIS run's cash rows are complete.

    A company analysis reads its ledger, so it takes every completed statement's extent (loaded
    by the caller); a file analysis reads one file, whose own extent is what covers its rows.
    """
    if state.get("ledger_view") is not None:
        return [e for e in (state.get("statement_extents") or []) if e]
    rows = list(state.get("transactions") or [])
    own = state.get("statement_extent") or statement_extent(rows) or extent_of_rows(rows)
    return [own] if own else []


def _groups(extents: list[dict[str, Any]]) -> list[tuple[date, date]]:
    """One (start, end) per account: chained statements joined, the rest apart."""
    chains: list[dict[str, Any]] = []
    for e in sorted(extents, key=lambda x: (str(x["start"]), str(x["end"]))):
        for c in chains:
            if (
                c["closing"] is not None
                and e.get("opening_cents") == c["closing"]
                and _day(e["start"]) >= _day(c["end"])
            ):
                c["end"], c["closing"] = e["end"], e.get("closing_cents")
                break
        else:
            chains.append({"start": e["start"], "end": e["end"], "closing": e.get("closing_cents")})
    return [(_day(c["start"]), _day(c["end"])) for c in chains]


def complete_months(extents: list[dict[str, Any]], months: list[str]) -> dict[str, bool] | None:
    """{month: covered from its first day to its last by every account}; None with no extent at all."""
    if not extents:
        return None
    groups = _groups(extents)
    flags = {}
    for m in months:
        first, last = month_bounds(m)
        flags[m] = all(start <= first and last <= end for start, end in groups)
    return flags


def covered_days(month: str, extents: list[dict[str, Any]]) -> tuple[int, int] | None:
    """The first and last day of `month` the extents cover (the widest account), if any."""
    first, last = month_bounds(month)
    best: tuple[int, int] | None = None
    for start, end in _groups(extents):
        lo, hi = max(start, first), min(end, last)
        if lo <= hi and (best is None or (hi - lo) > (best[1] - best[0])):
            best = (lo.day, hi.day)
    return best


def usable_months(series: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The latest run of consecutive COMPLETE months (an incomplete edge month is left out).

    What a monthly figure may be built from.

    A series whose months carry no completeness flag (coverage unknown) is returned as it is: it
    is the caller's to say that nothing proves those months whole.
    """
    if not any("complete" in m for m in series):
        return list(series)
    blocks: list[list[dict[str, Any]]] = []
    previous: str | None = None
    for m in series:
        if m.get("complete") is not True:
            previous = None
            continue
        if previous is not None and next_month(previous) == m["month"]:
            blocks[-1].append(m)
        else:
            blocks.append([m])
        previous = m["month"]
    return blocks[-1] if blocks else []


def gaps(series: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """Runs of months with no data between the first and last month of the series."""
    if len(series) < 2:
        return []
    have = {m["month"] for m in series}
    out: list[tuple[str, str]] = []
    run: list[str] = []
    for m in month_range(series[0]["month"], series[-1]["month"]):
        if m in have:
            if run:
                out.append((run[0], run[-1]))
                run = []
        else:
            run.append(m)
    return out




def annotate_series(
    series: list[dict[str, Any]], rows: list[dict[str, Any]], extents: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """The monthly series with what it covers, per month.

    `complete`: True / False, or None when no extent is known at all. An incomplete month says
    which days it covers (`covered`); a month inside the coverage with no rows is a real zero
    month and is added; one outside it stays missing. `top_out` is the month's largest outflow.
    """
    if not series:
        return series
    top: dict[str, dict[str, Any]] = {}
    # An outflow a person corrected away (a reversal of the same amount in the same month) is
    # no one-off: matched pairs are left out of the candidates.
    credits: dict[tuple[str, int], int] = {}
    for r in rows:
        day = str(r.get("transaction_date") or "")[:10]
        if len(day) == 10 and r.get("type") == "income":
            key = (day[:7], int(r.get("amount_cents") or 0))
            credits[key] = credits.get(key, 0) + 1
    for r in rows:
        day = str(r.get("transaction_date") or "")[:10]
        if len(day) < 10 or r.get("type") == "income":
            continue
        amount = int(r.get("amount_cents") or 0)
        if credits.get((day[:7], amount), 0) > 0:
            credits[(day[:7], amount)] -= 1
            continue
        if amount > (top.get(day[:7]) or {}).get("amount_cents", 0):
            top[day[:7]] = {"date": day, "amount_cents": amount, "description": str(r.get("description") or "")}
    have = {m["month"]: m for m in series}
    span = month_range(series[0]["month"], series[-1]["month"])
    flags = complete_months(extents, span)
    out: list[dict[str, Any]] = []
    for month in span:
        if month in have:
            entry = dict(have[month])
        elif flags and flags[month]:
            entry = {"month": month, "in": 0, "out": 0, "net": 0}
        else:
            continue
        entry["complete"] = None if flags is None else flags[month]
        if entry["complete"] is False:
            entry["covered"] = covered_days(month, extents)
        if month in top:
            entry["top_out"] = top[month]
        out.append(entry)
    return out
