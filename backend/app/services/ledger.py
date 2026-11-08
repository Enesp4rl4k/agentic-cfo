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

**One sale, two views.** A row rests on a `book` posting, a `document` or `cash`.
Doubt applies only within a basis: an invoice and its receipt are expected, and
reconciliation (app/services/reconciliation.py) ties them together. Profit comes
from the books where a month has them; otherwise from documents and from cash that
pays no document. Cash is what moved through the bank.

**Held analyses stay out.** Only a completed analysis is read, so a run the gate
held joins when it is approved, and a broken file never reaches the record.
Rows with no readable date stay out too: their period is unknown.
"""
from __future__ import annotations

import hashlib
import logging
import re
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
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
from app.models.open_item import OpenItem
from app.models.transaction import Transaction

logger = logging.getLogger(__name__)

# Rows identified by their content, across every file and source.
SOURCE_FINGERPRINT = "fingerprint"

ACTIVE = "active"
POSSIBLE_DUPLICATE = "possible_duplicate"
EXCLUDED = "excluded"

BOOK = "book"
DOCUMENT = "document"
CASH = "cash"

_CHUNK = 500
DUPLICATE_WINDOW_DAYS = 3    # as the anomaly agent's duplicate check


def _words(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", fold(text)).strip()


def day_of(when: datetime) -> date:
    """The UTC day: SQLite hands back naive datetimes, Postgres aware ones."""
    return when.astimezone(UTC).date() if when.tzinfo else when.date()


def _basis(tx: Transaction) -> str:
    if tx.account_code:
        return BOOK
    return DOCUMENT if tx.document_id else CASH


def _fingerprint(org_id: str, tx: Transaction) -> str:
    material = "|".join((
        org_id,
        day_of(tx.transaction_date).isoformat(),
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
) -> dict[tuple[int, str, str], list[tuple[date, str]]]:
    """Rows from other uploads around these dates: what a new row might repeat."""
    window = timedelta(days=DUPLICATE_WINDOW_DAYS)
    rows = await db.execute(
        select(
            CanonicalTransaction.id,
            CanonicalTransaction.transaction_date,
            CanonicalTransaction.amount_cents,
            CanonicalTransaction.direction,
            CanonicalTransaction.source_job_id,
            CanonicalTransaction.basis,
        ).where(
            CanonicalTransaction.org_id == org_id,
            CanonicalTransaction.ledger_status != EXCLUDED,
            CanonicalTransaction.transaction_date >= datetime.combine(min(days) - window, time.min, UTC),
            CanonicalTransaction.transaction_date <= datetime.combine(max(days) + window, time.max, UTC),
        )
    )
    found: dict[tuple[int, str, str], list[tuple[date, str]]] = defaultdict(list)
    for r in rows:
        if r.source_job_id != job_id:
            found[(r.amount_cents, r.direction, r.basis)].append((day_of(r.transaction_date), r.id))
    return found


def _repeats(
    others: dict[tuple[int, str, str], list[tuple[date, str]]], tx: Transaction
) -> str | None:
    """The nearest row this one may repeat, if any is close enough."""
    day = day_of(tx.transaction_date)
    near = [
        (abs((other - day).days), row_id)
        for other, row_id in others.get((tx.amount_kurus, tx.type, _basis(tx)), [])
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
    counts = {"new": 0, "already": 0, "possible_duplicate": 0, "no_date": 0, "settled": 0, "proposed": 0}
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
        if tx.document_id:
            # The document's own id beats its content: the same invoice is the
            # same money whatever the row around it says.
            usable.append((f"doc:{tx.document_id}", tx))
            continue
        print_ = _fingerprint(org_id, tx)
        seen[print_] += 1
        usable.append((f"fp:{print_}#{seen[print_]}", tx))
    if not usable:
        await _record(db, job, counts)
        return counts

    existing = await _existing(db, org_id, [rid for rid, _ in usable])
    others = await _others_by_money(
        db, org_id, job_id, [day_of(tx.transaction_date) for _, tx in usable],
    )

    for record_id, tx in usable:
        row = existing.get(record_id)
        if row is not None:
            # Same money, newer reading of it (a correction, a better account).
            row.category = tx.category
            row.account_code = tx.account_code or row.account_code
            row.basis = _basis(tx)
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
            "basis": _basis(tx),
            "duplicate_of": duplicate_of,
        })
        if not written:
            counts["already"] += 1
        elif duplicate_of:
            counts["possible_duplicate"] += 1
        else:
            counts["new"] += 1
    await _open_items(db, org_id, job_id, [tx for _, tx in usable])
    # Either side may arrive first: an invoice can close a line already here.
    from app.services.reconciliation import reconcile_org

    counts.update(await reconcile_org(db, org_id))
    await _record(db, job, counts)
    return counts


async def _open_items(db: AsyncSession, org_id: str, job_id: str, txs: list[Transaction]) -> None:
    """A document whose side we know opens an item; the same one twice does not."""
    insert = pg_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
    for tx in txs:
        if not (tx.document_id and tx.counterparty):
            continue
        await db.execute(
            insert(OpenItem).values(
                id=str(uuid.uuid4()),
                org_id=org_id,
                direction="receivable" if tx.type == "income" else "payable",
                instrument="invoice",
                document_id=tx.document_id,
                source_job_id=job_id,
                counterparty=tx.counterparty,
                description=tx.description,
                amount_cents=tx.amount_kurus,
                paid_cents=0,
                currency=tx.currency,
                issue_date=day_of(tx.transaction_date),
                due_date=tx.due_date,
                payment_note=tx.payment_note,
                status="open",
                created_at=datetime.now(UTC),
            ).on_conflict_do_nothing(index_elements=["org_id", "document_id"])
        )


async def _open_items_summary(db: AsyncSession, org_id: str) -> dict[str, int]:
    """What is outstanding, in TRY. Other currencies are counted, never converted."""
    totals = {"receivable_cents": 0, "payable_cents": 0, "no_due_date": 0, "other_currency": 0}
    rows = await db.execute(
        select(OpenItem.direction, OpenItem.amount_cents - OpenItem.paid_cents, OpenItem.currency, OpenItem.due_date)
        .where(OpenItem.org_id == org_id, OpenItem.status == "open")
    )
    for direction, amount, currency, due in rows:
        if due is None:
            totals["no_due_date"] += 1
        if currency != "TRY":
            totals["other_currency"] += 1
            continue
        totals["receivable_cents" if direction == "receivable" else "payable_cents"] += amount
    return totals


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


@dataclass(frozen=True)
class CompanyRows:
    """What the ledger counts: profit and cash are different views of one money."""

    profit: list[Any]       # book rows, or documents plus cash that pays no document
    cash: list[Any]         # bank movements, or postings where there is no statement
    possible_duplicates: int
    months: list[str]       # every month a counted row falls in
    rows: int               # rows the ledger counts, in either view or neither


def month_of(when: datetime) -> str:
    return day_of(when).strftime("%Y-%m")


async def company_rows(db: AsyncSession, org_id: str) -> CompanyRows:
    """The one reading of the ledger; the summary and the company view both use it."""
    from app.services.reconciliation import rows_settling_items

    rows = (await db.execute(
        select(
            CanonicalTransaction.id,
            CanonicalTransaction.source_record_id,
            CanonicalTransaction.transaction_date,
            CanonicalTransaction.amount_cents,
            CanonicalTransaction.currency,
            CanonicalTransaction.direction,
            CanonicalTransaction.category,
            CanonicalTransaction.account_code,
            CanonicalTransaction.counterparty,
            CanonicalTransaction.description,
            CanonicalTransaction.ledger_status,
            CanonicalTransaction.basis,
        ).where(
            CanonicalTransaction.org_id == org_id,
            CanonicalTransaction.ledger_status != EXCLUDED,
        ).order_by(CanonicalTransaction.transaction_date, CanonicalTransaction.id)
    )).all()
    settling = await rows_settling_items(db, org_id)
    counted = [r for r in rows if r.ledger_status != POSSIBLE_DUPLICATE]
    book_months = {month_of(r.transaction_date) for r in counted if r.basis == BOOK}
    cash_months = {month_of(r.transaction_date) for r in counted if r.basis == CASH}
    return CompanyRows(
        profit=[
            r for r in counted
            # The books already say what their month earned, and a settling line
            # is an invoice already counted, arriving.
            if (r.basis == BOOK or month_of(r.transaction_date) not in book_months)
            and not (r.basis == CASH and r.id in settling)
        ],
        # A posting list with no bank statement beside it is the best view of cash.
        cash=[
            r for r in counted
            if r.basis == CASH or (r.basis == BOOK and month_of(r.transaction_date) not in cash_months)
        ],
        possible_duplicates=len(rows) - len(counted),
        months=sorted({month_of(r.transaction_date) for r in counted}),
        rows=len(counted),
    )


async def ledger_summary(db: AsyncSession, org_id: str) -> dict[str, Any]:
    """The company's figures from the ledger, in kuruş. What awaits a person waits."""
    view = await company_rows(db, org_id)
    months = {m: {"cash_in_cents": 0, "cash_out_cents": 0} for m in view.months}
    for r in view.cash:
        key = "cash_in_cents" if r.direction == "income" else "cash_out_cents"
        months[month_of(r.transaction_date)][key] += r.amount_cents
    earned = [r for r in view.profit if r.category not in BILANCO_KATEGORILERI]
    return {
        "last_upload": await _last_upload(db, org_id),
        "open_items": await _open_items_summary(db, org_id),
        "rows": view.rows,
        "revenue_cents": sum(r.amount_cents for r in earned if r.direction == "income"),
        "expense_cents": sum(r.amount_cents for r in earned if r.direction != "income"),
        "possible_duplicates": view.possible_duplicates,
        "period": {"start": view.months[0] if view.months else None,
                   "end": view.months[-1] if view.months else None,
                   "months": len(view.months)},
        "months": [{"month": m, **months[m]} for m in view.months],
    }
