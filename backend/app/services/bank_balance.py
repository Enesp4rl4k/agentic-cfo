"""The balance a bank statement closes on, when the statement proves it.

A statement's running balance ("bakiye") is the one cash figure a company does
not have to reconstruct. It is believed only when it checks out: each row's
balance is the previous one plus that row's movement. That also says which way
the file is ordered, since banks export both oldest-first and newest-first. A
file whose balances do not chain (a merged batch, a missing row, a parser that
read a column wrong) closes on no balance at all: unknown, not guessed.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analysis_job import AnalysisJob, JobStatus


def _signed(tx: dict[str, Any]) -> int:
    amount = int(tx.get("amount_cents") or 0)
    return amount if tx.get("type") == "income" else -amount


def _chains(rows: list[dict[str, Any]]) -> bool:
    """Oldest first: every balance is the one before it plus this row's money."""
    return all(
        rows[i]["balance_cents"] == rows[i - 1]["balance_cents"] + _signed(rows[i])
        for i in range(1, len(rows))
    )


def chain_verified(counts: dict[str, Any] | None) -> bool:
    """False when the reader itself could not verify the statement's balance chain.

    `counts` is the run's ingest counts (state `ingest_counts`) or the stored ingest summary
    (`result_metadata["ingest"]`): both carry `balance_check` ("verified" | "unverified" | None for a
    file that is not a text statement) and `unaccounted` (rows the readers lost). A chain that checks
    out on the rows we hold is not a proven balance when the reader says it could not verify it, or
    when rows went missing: no balance, no extent, so no runway built on them.
    """
    c = counts or {}
    return c.get("balance_check") != "unverified" and not int(c.get("unaccounted") or 0)


def _chain_order(transactions: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    """The rows oldest first, when the statement's balances chain (in file order or reversed)."""
    rows = [t for t in transactions if t.get("balance_cents") is not None and t.get("transaction_date")]
    # One row proves nothing: there is nothing to chain it to.
    if len(rows) < 2 or len(rows) != len(transactions):
        return None
    for ordered in (rows, rows[::-1]):
        if _chains(ordered):
            return ordered
    return None


def closing_balance(transactions: list[dict[str, Any]]) -> dict[str, Any] | None:
    """{"date", "balance_cents"} the statement ends on, or None if it does not prove one."""
    ordered = _chain_order(transactions)
    if ordered is None:
        return None
    last = ordered[-1]
    return {"date": str(last["transaction_date"])[:10], "balance_cents": int(last["balance_cents"])}


def statement_extent(transactions: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The days a balance-proven statement covers and the balances it opens and closes on.

    {"start", "end", "opening_cents", "closing_cents"}: first and last transaction date (the data's
    own proven extent) and the balance before the first row / after the last. None when the
    balances do not chain. Two statements whose closing and opening balances meet are one account's
    consecutive statements (`app.services.coverage`).
    """
    ordered = _chain_order(transactions)
    if ordered is None:
        return None
    dates = sorted(str(t["transaction_date"])[:10] for t in ordered)
    first, last = ordered[0], ordered[-1]
    return {
        "start": dates[0],
        "end": dates[-1],
        "opening_cents": int(first["balance_cents"]) - _signed(first),
        "closing_cents": int(last["balance_cents"]),
    }


async def proven_balance(db: AsyncSession, org_id: str) -> dict[str, Any] | None:
    """The latest closing balance a completed statement proved, if any did."""
    jobs = (
        await db.execute(
            select(AnalysisJob.id, AnalysisJob.filename, AnalysisJob.result_metadata).where(
                AnalysisJob.org_id == org_id,
                AnalysisJob.status == JobStatus.COMPLETED,
            )
        )
    ).all()
    found = [
        {**m["closing_balance"], "job_id": job_id, "filename": filename}
        for job_id, filename, m in jobs
        if m and m.get("closing_balance") and chain_verified(m.get("ingest"))
    ]
    return max(found, key=lambda c: c["date"], default=None)


def balance_age(as_of: str, anchor: date, stale_after_days: int) -> tuple[int, bool]:
    """(days since the statement closed, whether that is older than the staleness limit).

    The one rule for how old a proven balance may be before it is shown as "last known": the
    cash radar and the forecast's runway both read it here.
    """
    age = max(0, (anchor - date.fromisoformat(str(as_of)[:10])).days)
    return age, age > stale_after_days


def latest_balance(*candidates: dict[str, Any] | None) -> dict[str, Any] | None:
    """The newest of the proven balances given (the first one on a tie), or None."""
    known = [c for c in candidates if c]
    return max(known, key=lambda c: str(c["date"])[:10], default=None)


async def proven_statements(db: AsyncSession, org_id: str) -> list[dict[str, Any]]:
    """The extents of the company's completed balance-proven statements (see `statement_extent`)."""
    metas = (
        await db.execute(
            select(AnalysisJob.result_metadata).where(
                AnalysisJob.org_id == org_id,
                AnalysisJob.status == JobStatus.COMPLETED,
            )
        )
    ).scalars().all()
    return [m["statement_extent"] for m in metas if m and m.get("statement_extent") and chain_verified(m.get("ingest"))]
