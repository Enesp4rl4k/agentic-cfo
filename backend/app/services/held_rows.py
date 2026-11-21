"""Rows waiting for a person: list them, release them into the books, or reject them.

Releasing is the human's answer to "I was not sure": the row becomes a
`Transaction` of its job and, when the job is complete, joins the company ledger
through the ledger's own idempotent append. A row whose currency is unknown can
be released only with a currency the person names. Rows of one document move
together, as they were held together.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.row_confidence import label, parse_confidence
from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.held_transaction import PENDING, REJECTED, RELEASED, HeldTransaction
from app.services.ingest.persist import build_transaction


async def pending_for_job(db: AsyncSession, job_id: str) -> list[HeldTransaction]:
    return list((await db.execute(
        select(HeldTransaction)
        .where(HeldTransaction.job_id == job_id, HeldTransaction.status == PENDING)
        .order_by(HeldTransaction.created_at, HeldTransaction.id)
    )).scalars().all())


async def pending_count(db: AsyncSession, org_id: str) -> int:
    return int((await db.execute(
        select(func.count()).select_from(HeldTransaction)
        .where(HeldTransaction.org_id == org_id, HeldTransaction.status == PENDING)
    )).scalar() or 0)


def describe(row: HeldTransaction) -> dict[str, Any]:
    p = row.payload
    confidence = parse_confidence(p.get("confidence"))
    return {
        "id": row.id,
        "job_id": row.job_id,
        "reasons": list(p.get("hold_reasons") or []),
        # Never a number for an unscored row.
        "confidence": confidence,
        "confidence_label": label(confidence),
        "amount_cents": p.get("amount_cents"),
        "currency": p.get("currency"),
        "type": p.get("type"),
        "description": p.get("description"),
        "vendor": p.get("vendor"),
        "transaction_date": p.get("transaction_date"),
        "document_id": p.get("document_id"),
    }


async def _with_document_mates(
    db: AsyncSession, job_id: str, picked: list[HeldTransaction]
) -> list[HeldTransaction]:
    documents = {r.payload.get("document_id") for r in picked if r.payload.get("document_id")}
    if not documents:
        return picked
    chosen = {r.id: r for r in picked}
    for r in await pending_for_job(db, job_id):
        if r.payload.get("document_id") in documents:
            chosen[r.id] = r
    return list(chosen.values())


async def resolve(
    db: AsyncSession,
    job: AnalysisJob,
    *,
    ids: list[str] | None,
    release: bool,
    user_id: str,
    currency: str | None = None,
) -> dict[str, Any]:
    """Release or reject pending rows of a job (all of them when `ids` is None). Commits."""
    waiting = await pending_for_job(db, job.id)
    wanted = None if ids is None else set(ids)
    picked = waiting if wanted is None else [r for r in waiting if r.id in wanted]
    picked = await _with_document_mates(db, job.id, picked)
    code = (currency or "").strip().upper() or None
    if code is not None and not (len(code) == 3 and code.isalpha()):
        raise ValueError("currency must be an ISO-4217 code")
    now = datetime.now(UTC)
    moved = 0
    blocked: list[str] = []
    for row in picked:
        payload = dict(row.payload)
        if release:
            if not str(payload.get("currency") or "").strip():
                if code is None:
                    blocked.append(row.id)
                    continue
                payload["currency"] = code
            if payload.get("type") not in ("income", "expense"):
                blocked.append(row.id)  # direction must be settled first
                continue
            db.add(build_transaction(job.id, payload))
        row.status = RELEASED if release else REJECTED
        row.resolved_at = now
        row.resolved_by = user_id
        moved += 1
    await db.commit()
    appended = None
    if release and moved and job.org_id and job.status == JobStatus.COMPLETED:
        from app.services.ledger import append_job

        appended = await append_job(db, job.id)
    return {
        "resolved": moved,
        "blocked": blocked,
        "still_waiting": len(await pending_for_job(db, job.id)),
        "ledger": appended,
    }
