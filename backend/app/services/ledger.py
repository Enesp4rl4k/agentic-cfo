"""The company ledger: one record of a company's money, whichever way it arrived.

Every upload was an island: the same file analysed twice was two analyses, and
January–March plus February–April said nothing about the months they share
(plan v9 §K1 / §V5 F1). `canonical_transactions` is the record; a completed
analysis appends to it.

**Identity.** A row is its content: organisation, day, signed amount, direction
and normalised description, hashed. Re-reading a file therefore writes nothing,
whichever file it arrived in. Two identical payments in one file are two
payments, so the nth occurrence is part of the identity: the same file twice
still gives the same two identities.

**Doubt.** The same amount and direction within a few days, from another upload,
may be one payment seen twice: a bank line and its invoice rarely share a date
(live: a January file's ₺285.000 sat a day away from the ledger's and was counted
twice under a same-day rule). The machine cannot know. The row is kept as
`possible_duplicate`, out of the totals, until a person decides. Nothing is merged
or deleted, and a wrong suspicion costs one click.

**Held analyses stay out.** Only a completed analysis is read, so a run the gate
held joins when it is approved, and a broken file never reaches the record.
Rows with no readable date stay out too: their period is unknown.
"""
from __future__ import annotations

import hashlib
import logging
import re
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tdhp import BILANCO_KATEGORILERI
from app.core.turkish import fold
from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.canonical_transaction import CanonicalTransaction
from app.models.transaction import Transaction

logger = logging.getLogger(__name__)

# Rows identified by their content, across every file and source.
SOURCE_FINGERPRINT = "fingerprint"

ACTIVE = "active"
POSSIBLE_DUPLICATE = "possible_duplicate"
EXCLUDED = "excluded"

_CHUNK = 500
DUPLICATE_WINDOW_DAYS = 3    # as the anomaly agent's duplicate check


def _words(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", fold(text)).strip()


def _day(when: datetime) -> date:
    """The UTC day: SQLite hands back naive datetimes, Postgres aware ones."""
    return when.astimezone(UTC).date() if when.tzinfo else when.date()


def _fingerprint(org_id: str, tx: Transaction) -> str:
    material = "|".join((
        org_id,
        _day(tx.transaction_date).isoformat(),
        str(tx.amount_kurus),
        tx.type,
        _words(tx.description or tx.vendor),
    ))
    return hashlib.sha256(material.encode()).hexdigest()


async def _existing(db: AsyncSession, org_id: str, ids: list[str]) -> dict[str, CanonicalTransaction]:
    found: dict[str, CanonicalTransaction] = {}
    for i in range(0, len(ids), _CHUNK):
        rows = await db.execute(
            select(CanonicalTransaction).where(
                CanonicalTransaction.org_id == org_id,
                CanonicalTransaction.source_type == SOURCE_FINGERPRINT,
                CanonicalTransaction.source_record_id.in_(ids[i:i + _CHUNK]),
            )
        )
        found.update({r.source_record_id: r for r in rows.scalars()})
    return found


async def _others_by_money(
    db: AsyncSession, org_id: str, job_id: str, days: list[date]
) -> dict[tuple[int, str], list[tuple[date, str]]]:
    """Rows from other uploads around these dates: what a new row might repeat."""
    window = timedelta(days=DUPLICATE_WINDOW_DAYS)
    rows = await db.execute(
        select(
            CanonicalTransaction.id,
            CanonicalTransaction.transaction_date,
            CanonicalTransaction.amount_cents,
            CanonicalTransaction.direction,
            CanonicalTransaction.source_job_id,
        ).where(
            CanonicalTransaction.org_id == org_id,
            CanonicalTransaction.ledger_status != EXCLUDED,
            CanonicalTransaction.transaction_date >= datetime.combine(min(days) - window, time.min, UTC),
            CanonicalTransaction.transaction_date <= datetime.combine(max(days) + window, time.max, UTC),
        )
    )
    found: dict[tuple[int, str], list[tuple[date, str]]] = defaultdict(list)
    for r in rows:
        if r.source_job_id != job_id:
            found[(r.amount_cents, r.direction)].append((_day(r.transaction_date), r.id))
    return found


def _repeats(
    others: dict[tuple[int, str], list[tuple[date, str]]], tx: Transaction
) -> str | None:
    """The nearest row this one may repeat, if any is close enough."""
    day = _day(tx.transaction_date)
    near = [
        (abs((other - day).days), row_id)
        for other, row_id in others.get((tx.amount_kurus, tx.type), [])
        if abs((other - day).days) <= DUPLICATE_WINDOW_DAYS
    ]
    return min(near)[1] if near else None


async def _insert_ignoring_races(db: AsyncSession, values: dict[str, Any]) -> int:
    """Insert one row; a concurrent append of the same identity is not an error."""
    insert = pg_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
    result = await db.execute(
        insert(CanonicalTransaction).values(**values).on_conflict_do_nothing(
            index_elements=["org_id", "source_type", "source_record_id"]
        )
    )
    return int(result.rowcount or 0)


async def append_job(db: AsyncSession, job_id: str) -> dict[str, int]:
    """Append a completed analysis to its company's ledger. Idempotent; commits."""
    counts = {"new": 0, "already": 0, "possible_duplicate": 0, "no_date": 0}
    job = await db.get(AnalysisJob, job_id)
    if job is None or not job.org_id or job.status != JobStatus.COMPLETED:
        return counts
    org_id = str(job.org_id)

    txs = (await db.execute(
        select(Transaction).where(Transaction.job_id == job_id).order_by(Transaction.transaction_date)
    )).scalars().all()

    usable: list[tuple[str, Transaction]] = []
    seen: Counter[str] = Counter()
    for tx in txs:
        if tx.date_is_estimated:
            counts["no_date"] += 1
            continue
        if not tx.amount_kurus:
            continue
        print_ = _fingerprint(org_id, tx)
        seen[print_] += 1
        usable.append((f"fp:{print_}#{seen[print_]}", tx))
    if not usable:
        await _record(db, job, counts)
        return counts

    existing = await _existing(db, org_id, [rid for rid, _ in usable])
    others = await _others_by_money(
        db, org_id, job_id, [_day(tx.transaction_date) for _, tx in usable],
    )

    for record_id, tx in usable:
        row = existing.get(record_id)
        if row is not None:
            # Same money, newer reading of it (a correction, a better account).
            row.category = tx.category
            row.account_code = tx.account_code or row.account_code
            counts["already"] += 1
            continue
        duplicate_of = _repeats(others, tx)
        written = await _insert_ignoring_races(db, {
            "org_id": org_id,
            "source_type": SOURCE_FINGERPRINT,
            "source_record_id": record_id,
            "source_job_id": job_id,
            "transaction_date": tx.transaction_date,
            "amount_cents": tx.amount_kurus,
            "currency": tx.currency,
            "direction": tx.type,
            "category": tx.category,
            "account_code": tx.account_code,
            "counterparty": tx.vendor,
            "description": tx.description,
            "confidence": round(float(tx.confidence) * 100) if tx.confidence is not None else None,
            "ledger_status": POSSIBLE_DUPLICATE if duplicate_of else ACTIVE,
            "duplicate_of": duplicate_of,
        })
        if not written:
            counts["already"] += 1
        elif duplicate_of:
            counts["possible_duplicate"] += 1
        else:
            counts["new"] += 1
    await _record(db, job, counts)
    return counts


async def _record(db: AsyncSession, job: AnalysisJob, counts: dict[str, int]) -> None:
    """The answer to "what did this upload add?", kept on the job."""
    job.result_metadata = {**(job.result_metadata or {}), "ledger": dict(counts)}
    await db.commit()


async def backfill(db: AsyncSession) -> dict[str, int]:
    """Append every completed analysis, oldest first. Safe to run again."""
    ids = (await db.execute(
        select(AnalysisJob.id)
        .where(AnalysisJob.status == JobStatus.COMPLETED, AnalysisJob.org_id.is_not(None))
        .order_by(AnalysisJob.created_at)
    )).scalars().all()
    totals: Counter[str] = Counter()
    for job_id in ids:
        totals.update(await append_job(db, job_id))
    return {"jobs": len(ids), "new": totals["new"], "already": totals["already"],
            "possible_duplicate": totals["possible_duplicate"], "no_date": totals["no_date"]}


async def _last_upload(db: AsyncSession, org_id: str) -> dict[str, Any] | None:
    """What the newest analysis added: the answer to "did my file count?"."""
    jobs = (await db.execute(
        select(AnalysisJob)
        .where(AnalysisJob.org_id == org_id, AnalysisJob.status == JobStatus.COMPLETED)
        .order_by(AnalysisJob.created_at.desc())
        .limit(20)
    )).scalars()
    for job in jobs:
        added = (job.result_metadata or {}).get("ledger")
        if added:
            return {"filename": job.filename, **added}
    return None


async def ledger_summary(db: AsyncSession, org_id: str) -> dict[str, Any]:
    """The company's figures from the ledger, in kuruş. Possible duplicates wait."""
    rows = await db.execute(
        select(
            CanonicalTransaction.transaction_date,
            CanonicalTransaction.amount_cents,
            CanonicalTransaction.direction,
            CanonicalTransaction.category,
            CanonicalTransaction.ledger_status,
        ).where(
            CanonicalTransaction.org_id == org_id,
            CanonicalTransaction.ledger_status != EXCLUDED,
        )
    )
    months: dict[str, dict[str, int]] = defaultdict(lambda: {"cash_in_cents": 0, "cash_out_cents": 0})
    revenue = expense = count = possible = 0
    for when, amount, direction, category, status in rows:
        if status == POSSIBLE_DUPLICATE:
            possible += 1
            continue
        count += 1
        month = months[_day(when).strftime("%Y-%m")]
        month["cash_in_cents" if direction == "income" else "cash_out_cents"] += amount
        if category in BILANCO_KATEGORILERI:
            continue
        if direction == "income":
            revenue += amount
        else:
            expense += amount
    names = sorted(months)
    return {
        "last_upload": await _last_upload(db, org_id),
        "rows": count,
        "revenue_cents": revenue,
        "expense_cents": expense,
        "possible_duplicates": possible,
        "period": {"start": names[0] if names else None, "end": names[-1] if names else None,
                   "months": len(names)},
        "months": [{"month": m, **months[m]} for m in names],
    }
