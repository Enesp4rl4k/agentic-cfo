"""Shared fixtures for the cash-radar and Monday-briefing tests: one place that turns
hand-written rows into a completed upload and its ledger entries."""

from __future__ import annotations

from typing import Any

from app.core.dates import parse_transaction_date
from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.transaction import Transaction
from app.services.ledger import append_job


def statement(day: str, cents: int) -> dict[str, Any]:
    return {"closing_balance": {"date": day, "balance_cents": cents}}


async def upload(
    client,
    org_id: str,
    *rows: dict[str, Any],
    meta: dict | None = None,
    status: JobStatus = JobStatus.COMPLETED,
) -> str:
    async with client._maker() as db:
        job = AnalysisJob(
            filename="test.csv",
            file_path="/test.csv",
            file_type="csv",
            org_id=org_id,
            status=status,
            result_metadata=meta,
        )
        db.add(job)
        await db.flush()
        for r in rows:
            when, estimated = parse_transaction_date(r["transaction_date"])
            db.add(
                Transaction(
                    job_id=job.id,
                    amount_kurus=r["amount_cents"],
                    currency=r.get("currency", "TRY"),
                    type=r["type"],
                    category=r.get("category", "other_expense"),
                    description=r.get("description"),
                    transaction_date=when,
                    date_is_estimated=estimated,
                    document_id=r.get("document_id"),
                    due_date=r.get("due_date"),
                    vendor=r.get("counterparty") or r.get("vendor"),
                )
            )
        await db.commit()
        await append_job(db, job.id)
        return job.id
