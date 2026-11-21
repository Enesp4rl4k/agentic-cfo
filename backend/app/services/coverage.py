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

from app.services.bank_balance import chain_verified, statement_extent


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


EDGE_TOLERANCE_DAYS = 5
"""Days with no transaction at a statement's start or end that still leave that month complete.

An ASSUMPTION, always disclosed: an export that starts on the 3rd or ends on the 29th usually just
has no transaction on the weekend or holiday days around the edge. Used only where the file states
no period; a stated period or a chain of statements is proof and needs no tolerance."""


def apply_period(
    extent: dict[str, Any] | None, period: dict[str, Any] | None, filename: str | None = None
) -> dict[str, Any] | None:
    """The extent with the period the file STATES, edge by edge, where the data agrees with it.

    A header says what the statement is meant to cover; it is evidence for an edge only when the
    rows say the same: the stated end counts when the last transaction (= the closing balance's
    date) is within `EDGE_TOLERANCE_DAYS` of it, the stated start when the first transaction is.
    Then that edge is proven (`start_stated` / `end_stated`) and the header explains the few quiet
    days. When they disagree the header is ignored for that edge (the actual first/last
    transaction stands, the tolerance rule applies) and the disagreement is recorded in `mismatch`
    so the message can say it. Never proven on a contradicted header.
    """
    if extent is None:
        return None
    out = {k: v for k, v in extent.items() if k not in ("stated", "mismatch")}
    out.update(start_stated=False, end_stated=False)
    if filename and not out.get("filename"):
        out["filename"] = filename
    if period and period["start"] <= str(extent["start"]) and str(extent["end"]) <= period["end"]:
        mismatch: list[dict[str, str]] = []
        if (_day(extent["start"]) - _day(period["start"])).days <= EDGE_TOLERANCE_DAYS:
            out.update(start=period["start"], start_stated=True)
        else:
            mismatch.append({"edge": "start", "stated": period["start"], "actual": str(extent["start"])})
        if (_day(period["end"]) - _day(extent["end"])).days <= EDGE_TOLERANCE_DAYS:
            out.update(end=period["end"], end_stated=True)
        else:
            mismatch.append({"edge": "end", "stated": period["end"], "actual": str(extent["end"])})
        if mismatch:
            out["mismatch"] = mismatch
    return out


def extents_for(state: dict[str, Any]) -> list[dict[str, Any]]:
    """The extents that say which months of THIS run's cash rows are complete.

    A company analysis reads its ledger, so it takes every completed statement's extent (loaded
    by the caller); a file analysis reads one file, whose own extent is what covers its rows.
    """
    if state.get("ledger_view") is not None:
        return [e for e in (state.get("statement_extents") or []) if e]
    rows = list(state.get("transactions") or [])
    chained = chain_verified(state.get("ingest_counts"))
    # A chain the reader could not verify proves no balances (and so no join): only the dates stand.
    own = (state.get("statement_extent") or statement_extent(rows) if chained else None) or extent_of_rows(rows)
    path = str(state.get("file_path") or "").replace("\\", "/").rsplit("/", 1)[-1] or None
    own = apply_period(own, state.get("statement_period"), path)
    return [own] if own else []


def _edge(extent: dict[str, Any], which: str) -> bool:
    """Whether the extent's start/end edge is proven (a stated period the data agrees with)."""
    return bool(extent.get(f"{which}_stated", extent.get("stated")))


def _groups(extents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One group per account: statements whose balances meet are joined, the rest apart.

    A group is {start, end, start_proven, end_proven, name}: the days it covers, and whether each
    edge is proven (stated period, or a join) or only the first/last transaction.
    """
    chains: list[dict[str, Any]] = []
    for e in sorted(extents, key=lambda x: (str(x["start"]), str(x["end"]))):
        for c in chains:
            if (
                c["closing"] is not None
                and e.get("opening_cents") == c["closing"]
                and _day(e["start"]) >= _day(c["end"])
            ):
                c.update(end=e["end"], closing=e.get("closing_cents"), end_proven=_edge(e, "end"))
                break
        else:
            chains.append({
                "start": e["start"], "end": e["end"], "closing": e.get("closing_cents"),
                "start_proven": _edge(e, "start"), "end_proven": _edge(e, "end"),
                "name": e.get("filename") or "adsız ekstre",
            })
    return [
        {**c, "start": _day(c["start"]), "end": _day(c["end"])} for c in chains
    ]


def _judge(group: dict[str, Any], month: str) -> tuple[bool, list[dict[str, Any]]]:
    """(is the month complete for this account, the edges that rely on the tolerance)."""
    first, last = month_bounds(month)
    start, end = group["start"], group["end"]
    if start > last or end < first:
        return False, []
    assumed: list[dict[str, Any]] = []
    if start > first:
        missing = (start - first).days
        if group["start_proven"] or missing > EDGE_TOLERANCE_DAYS:
            return False, []
        assumed.append({"edge": "start", "days": missing})
    if end < last:
        missing = (last - end).days
        if group["end_proven"] or missing > EDGE_TOLERANCE_DAYS:
            return False, []
        assumed.append({"edge": "end", "days": missing})
    return True, assumed


def complete_months(extents: list[dict[str, Any]], months: list[str]) -> dict[str, bool] | None:
    """{month: covered by every account}; None with no extent at all.

    Covered means from the first day to the last, or, at an edge the file does not prove, within
    `EDGE_TOLERANCE_DAYS` of it (`assumed_edges` says where that was assumed).
    """
    if not extents:
        return None
    groups = _groups(extents)
    return {m: all(_judge(g, m)[0] for g in groups) for m in months}


def assumed_edges(extents: list[dict[str, Any]], month: str) -> list[dict[str, Any]]:
    """The edges of a complete month that rest on the tolerance, not on proof."""
    out: list[dict[str, Any]] = []
    for g in _groups(extents):
        out.extend(_judge(g, month)[1])
    return out


def short_accounts(extents: list[dict[str, Any]], month: str) -> list[dict[str, Any]]:
    """The accounts (statements) that do not cover `month`, when there is more than one account."""
    groups = _groups(extents)
    if len(groups) < 2:
        return []
    return [
        {"name": g["name"], "start": g["start"].isoformat(), "end": g["end"].isoformat()}
        for g in groups if not _judge(g, month)[0]
    ]


def covered_days(month: str, extents: list[dict[str, Any]]) -> tuple[int, int] | None:
    """The first and last day of `month` the extents cover (the widest account), if any."""
    first, last = month_bounds(month)
    best: tuple[int, int] | None = None
    for g in _groups(extents):
        lo, hi = max(g["start"], first), min(g["end"], last)
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
    mismatches = [x for e in extents for x in e.get("mismatch") or []]
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
            if short_accounts(extents, month):
                entry["short"] = short_accounts(extents, month)
        elif entry["complete"] and assumed_edges(extents, month):
            entry["assumed"] = assumed_edges(extents, month)
        found = [x for x in mismatches if str(x["actual"])[:7] == month]
        if found:
            entry["header_mismatch"] = found
        if month in top:
            entry["top_out"] = top[month]
        out.append(entry)
    return out
