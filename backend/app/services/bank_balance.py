"""The balance a bank statement closes on, when the statement proves it.

A statement's running balance ("bakiye") is the one cash figure a company does
not have to reconstruct. It is believed only when it checks out: each row's
balance is the previous one plus that row's movement. That also says which way
the file is ordered, since banks export both oldest-first and newest-first. A
file whose balances do not chain (a merged batch, a missing row, a parser that
read a column wrong) closes on no balance at all: unknown, not guessed.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.currency_totals import normalise
from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.transaction import Transaction


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
    """{"date", "balance_cents"} the statement ends on, or None if it does not prove one.

    Plus "currency" when every row names the same one: a balance is an amount, and an amount has a currency.
    Rows that name none or disagree leave it out: the balance's currency is then unknown, never assumed."""
    rows = [t for t in transactions if t.get("balance_cents") is not None and t.get("transaction_date")]
    # One row proves nothing: there is nothing to chain it to.
    if len(rows) < 2 or len(rows) != len(transactions):
        return None
    for ordered in (rows, rows[::-1]):
        if _chains(ordered):
            last = ordered[-1]
            proven = {"date": str(last["transaction_date"])[:10], "balance_cents": int(last["balance_cents"])}
            codes = {normalise(t.get("currency")) for t in transactions}
            if len(codes) == 1 and "" not in codes:
                proven["currency"] = codes.pop()
            return proven
    return None


async def proven_balance(db: AsyncSession, org_id: str) -> dict[str, Any] | None:
    """The latest closing balance a completed statement proved, if any did.

    Carries its "currency" ("" when unknown). A balance stored before currencies were kept takes the one
    currency its statement's rows share; if they share none, it stays unknown."""
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
    latest = max(found, key=lambda c: c["date"], default=None)
    if latest is None:
        return None
    code = normalise(latest.get("currency"))
    if not code:
        rows = await db.execute(select(Transaction.currency).where(Transaction.job_id == latest["job_id"]))
        codes = {normalise(c) for c in rows.scalars().all()}
        code = codes.pop() if len(codes) == 1 else ""
    return {**latest, "currency": code}
