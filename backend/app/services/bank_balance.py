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


def closing_balance(transactions: list[dict[str, Any]]) -> dict[str, Any] | None:
    """{"date", "balance_cents"} the statement ends on, or None if it does not prove one."""
    rows = [t for t in transactions if t.get("balance_cents") is not None and t.get("transaction_date")]
    # One row proves nothing: there is nothing to chain it to.
    if len(rows) < 2 or len(rows) != len(transactions):
        return None
    for ordered in (rows, rows[::-1]):
        if _chains(ordered):
            last = ordered[-1]
            return {"date": str(last["transaction_date"])[:10], "balance_cents": int(last["balance_cents"])}
    return None


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
        if m and m.get("closing_balance")
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
