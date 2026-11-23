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

**A document's identity.** An invoice is its own row, whichever file or source brought it
(`doc:<id>` for a UUID or GİB number). A free-form number ("A-001", "2024-01") is only unique
among one issuer's invoices, so it also carries the counterparty and the side: `inv:<s|p>:<party>:<no>`
(app/core/invoice_identity.py; plan v10 G23). A free-form number with no counterparty keeps the
old `doc:<no>` key and is reported (`no_counterparty`), never guessed.

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
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.currency_totals import (
    DEFAULT_BASE,
    EffectiveBase,
    foreign_summaries,
    normalise,
    split_by_currency,
)
from app.core.invoice_identity import (
    document_key,
    lacks_counterparty,
)
from app.core.tdhp import BILANCO_KATEGORILERI
from app.core.turkish import fold
from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.canonical_transaction import CanonicalTransaction
from app.models.open_item import OpenItem
from app.models.organization import Organization
from app.models.transaction import Transaction
from app.services.ledger_base import base_currency_of, confirmed_base_of, effective_base_of
from app.services.ledger_documents import (
    ACTIVE,
    BOOK,
    CASH,
    DOCUMENT,
    DUPLICATE_WINDOW_DAYS,
    EXCLUDED,
    POSSIBLE_DUPLICATE,
    base_row_id,
    basis_of,
    day_of,
    drop_open_item,
    existing_rows,
    job_transactions,
    load_aliases,
    open_item_for_row,
    open_items,
    others_by_money,
    repeats,
    same_document_other_id,
    same_number_match,
    same_number_rows,
    source_transaction,
    split_same_key,
    variant_of,
)
from app.services.ledger_period import LedgerPeriod, Period, current_month, resolve_period

logger = logging.getLogger(__name__)

# Names other modules import from here; they live in `ledger_documents` (the 600-line ceiling, plan v11 F2).
__all__ = [
    "ACTIVE",
    "BOOK",
    "CASH",
    "DOCUMENT",
    "DUPLICATE_WINDOW_DAYS",
    "EXCLUDED",
    "POSSIBLE_DUPLICATE",
    "Period",
    "base_currency_of",
    "confirmed_base_of",
    "day_of",
    "drop_open_item",
    "effective_base_of",
    "job_transactions",
    "load_aliases",
    "open_item_for_row",
    "source_transaction",
    "variant_of",
]

# Rows identified by their content, across every file and source.
SOURCE_FINGERPRINT = "fingerprint"
# A category correction on a closed month: a reversing row and a corrected row, booked in
# the first open month (services/ledger_correction.py). Neither is a payment or a new
# upload, so duplicate detection and reconciliation leave them alone.
SOURCE_CORRECTION = "correction"



_CHUNK = 500


async def lock_org(db: AsyncSession, org_id: str) -> None:
    """Serialise ledger writers and month closes of one organisation (no-op on SQLite).

    The organisation row is always locked first (corrections, `donem_kilidi.kilitle`,
    `append_job`), so the lock state read afterwards is the state at commit.
    """
    await db.execute(select(Organization.id).where(Organization.id == org_id).with_for_update())


def correction_number(source_record_id: str) -> int:
    """n of a correction row id `<record>~k<n>-iptal|yeni`."""
    return int(source_record_id.rsplit("~k", 1)[1].split("-")[0])


async def effective_categories(db: AsyncSession, org_id: str) -> dict[str, str | None]:
    """Original row id -> the category its latest correction gave it (closed months only).

    A closed month's original row keeps its old category; its effective one is the
    latest corrected row's. Readers that show or match categories use this.
    """
    rows = (await db.execute(
        select(CanonicalTransaction.corrects_id, CanonicalTransaction.source_record_id,
               CanonicalTransaction.category)
        .where(CanonicalTransaction.org_id == org_id,
               CanonicalTransaction.corrects_id.is_not(None),
               CanonicalTransaction.source_record_id.like("%-yeni"))
    )).all()
    latest: dict[str, tuple[int, str | None]] = {}
    for corrects_id, record_id, category in rows:
        n = correction_number(record_id)
        if corrects_id not in latest or n > latest[corrects_id][0]:
            latest[corrects_id] = (n, category)
    return {k: v[1] for k, v in latest.items()}


def _words(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", fold(text)).strip()






def _fingerprint(org_id: str, tx: Transaction) -> str:
    material = "|".join((
        org_id,
        day_of(tx.transaction_date).isoformat(),
        str(tx.amount_kurus),
        tx.type,
        _words(tx.description or tx.vendor),
    ))
    return hashlib.sha256(material.encode()).hexdigest()












async def _insert_ignoring_races(db: AsyncSession, values: dict[str, Any]) -> int:
    """Insert one row; a concurrent append of the same identity is not an error."""
    insert = pg_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
    result = await db.execute(
        insert(CanonicalTransaction).values(**values).on_conflict_do_nothing(
            index_elements=["org_id", "source_type", "source_record_id"]
        )
    )
    return int(result.rowcount or 0)




def record_ids(
    org_id: str, txs: list[Transaction], aliases: dict[str, str] | None = None
) -> tuple[list[tuple[str, Transaction]], int]:
    """Each transaction the ledger counts, with its `source_record_id`; and how many had no date.

    The one place that says which ledger row a transaction is, so a correction finds the
    row the append wrote.
    """
    no_date = 0
    usable: list[tuple[str, Transaction]] = []
    seen: Counter[str] = Counter()
    for tx in txs:
        if tx.date_is_estimated:
            no_date += 1
            continue
        if not tx.amount_kurus:
            continue
        if tx.document_id:
            # The document's own id beats its content: the same invoice is the
            # same money whatever the row around it says, and whichever source
            # (file, ERP, e-invoice) brought it (G2). A free-form number also
            # carries its counterparty and side, as it is only unique among
            # one issuer's invoices (G23).
            usable.append((document_key(org_id, tx.document_id, tx.counterparty, tx.type, aliases), tx))
            continue
        print_ = _fingerprint(org_id, tx)
        seen[print_] += 1
        usable.append((f"fp:{print_}#{seen[print_]}", tx))
    return usable, no_date














async def append_job(db: AsyncSession, job_id: str) -> dict[str, int]:
    """Append a completed analysis to its company's ledger. Idempotent; commits."""
    counts = {
        "new": 0, "already": 0, "possible_duplicate": 0, "no_date": 0, "settled": 0, "proposed": 0,
        "no_counterparty": 0, "many_versions": 0,
    }
    job = await db.get(AnalysisJob, job_id)
    if job is None or not job.org_id or job.status != JobStatus.COMPLETED:
        return counts
    org_id = str(job.org_id)

    aliases = await load_aliases(db, org_id)
    usable, counts["no_date"] = record_ids(org_id, await job_transactions(db, job_id), aliases)
    if not usable:
        await _record(db, job, counts)
        return counts

    # Org row first, as corrections and month closes do: a close racing this append is
    # serial, so the closed months read below are the ones at commit.
    await lock_org(db, org_id)
    # An invoice number with no counterparty cannot be told from another supplier's: counted
    # under its old key, and said so, so that a person can supply the counterparty.
    counts["no_counterparty"] = sum(1 for rid, _ in usable if lacks_counterparty(rid))
    if counts["no_counterparty"]:
        logger.warning(
            "ledger: %d invoice(s) with a free-form number and no counterparty (job %s)",
            counts["no_counterparty"], job_id,
        )
    existing = await existing_rows(db, org_id, [rid for rid, _ in usable])
    usable, variants, counts["many_versions"] = await split_same_key(
        db, org_id, job_id, usable, existing, aliases
    )
    # Months the accountant closed: their rows do not change, and money that belongs
    # to them but arrives now is written into the first open month.
    from app.services.donem_kilidi import ilk_acik_donem, kilitli_donemler

    kilitli = await kilitli_donemler(db, org_id)
    others = await others_by_money(
        db, org_id, job_id, [day_of(tx.transaction_date) for _, tx in usable],
    )
    same_number = await same_number_rows(db, org_id, job_id, usable)
    tx_cache: dict[str, list[Transaction]] = {}
    held: set[str] = set()  # rows waiting for a person: they put no money into the radar

    for record_id, tx in usable:
        row = existing.get(record_id)
        if row is not None:
            if row.ledger_status != ACTIVE:
                held.add(record_id)
            if month_of(row.transaction_date) in kilitli:
                counts["already"] += 1  # a closed month is not rewritten
                continue
            # Same money, newer reading of it (a correction, a better account).
            row.category = tx.category
            row.account_code = tx.account_code or row.account_code
            row.basis = basis_of(tx)
            counts["already"] += 1
            continue
        duplicate_of = (
            base_row_id(existing, record_id) if record_id in variants
            else repeats(others, tx, record_id)
            or await same_number_match(db, org_id, tx, record_id, same_number, aliases, tx_cache)
            or await same_document_other_id(db, tx, record_id, others, aliases, tx_cache)
        )
        if duplicate_of:
            held.add(record_id)
        tarih, asil_tarih, asil_donem = tx.transaction_date, None, None
        ay = month_of(tx.transaction_date)
        if ay in kilitli:
            hedef = ilk_acik_donem(ay, kilitli)
            asil_tarih, asil_donem = tx.transaction_date, ay
            tarih = datetime(int(hedef[:4]), int(hedef[5:7]), 1, tzinfo=UTC)
        written = await _insert_ignoring_races(db, {
            "org_id": org_id,
            "source_type": SOURCE_FINGERPRINT,
            "source_record_id": record_id,
            "source_job_id": job_id,
            "transaction_date": tarih,
            "asil_tarih": asil_tarih,
            "asil_donem": asil_donem,
            "amount_cents": tx.amount_kurus,
            "currency": normalise(tx.currency) or DEFAULT_BASE,  # the column's own default
            "direction": tx.type,
            "category": tx.category,
            "account_code": tx.account_code,
            "counterparty": tx.vendor,
            "description": tx.description,
            "confidence": round(float(tx.confidence) * 100) if tx.confidence is not None else None,
            "ledger_status": POSSIBLE_DUPLICATE if duplicate_of else ACTIVE,
            "basis": basis_of(tx),
            "duplicate_of": duplicate_of,
        })
        if not written:
            counts["already"] += 1
        elif duplicate_of:
            counts["possible_duplicate"] += 1
        else:
            counts["new"] += 1
    await open_items(db, org_id, job_id, [(rid, tx) for rid, tx in usable if rid not in held])
    # Either side may arrive first: an invoice can close a line already here.
    from app.services.reconciliation import reconcile_org

    counts.update(await reconcile_org(db, org_id))
    await _record(db, job, counts)
    return counts












async def _open_items_summary(db: AsyncSession, org_id: str, currency: str = DEFAULT_BASE) -> dict[str, int]:
    """What is outstanding, in `currency` (the effective base). Other currencies are counted, never converted."""
    totals = {"receivable_cents": 0, "payable_cents": 0, "no_due_date": 0, "other_currency": 0}
    rows = await db.execute(
        select(OpenItem.direction, OpenItem.amount_cents - OpenItem.paid_cents, OpenItem.currency, OpenItem.due_date)
        .where(OpenItem.org_id == org_id, OpenItem.status == "open")
    )
    for direction, amount, item_currency, due in rows:
        if due is None:
            totals["no_due_date"] += 1
        if normalise(item_currency) != currency:
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
    months: list[str]       # every month a counted row falls in, inside the period
    rows: int               # rows the ledger counts, in either view or neither
    period: LedgerPeriod    # the period these rows were read for
    # Correction-pair rows in `profit` whose original belongs to a period outside this one:
    # row id -> that period ("2025-09"), so a screen can say "correction from an earlier period".
    reclass_of_period: dict[str, str]
    base_currency: str      # the currency figures are computed in; rows in any other are never added to it
    effective: EffectiveBase  # how that currency was decided (confirmed / single / ambiguous / no data)


def month_of(when: datetime) -> str:
    """The row's month. `transaction_date` is the document's calendar day at 00:00 UTC by
    construction (`core.dates.parse_transaction_date`: the only ingest path), so the UTC
    month is the calendar month, and it is the same month a period lock closes."""
    return day_of(when).strftime("%Y-%m")



async def company_rows(db: AsyncSession, org_id: str, period: Period | None = None) -> CompanyRows:
    """The one reading of the ledger; the summary and the company view both use it.

    Only rows booked in the period are returned (default: the last 12 months of data).
    A row belongs to the month it is booked in (`transaction_date`), so a late item
    written into the first open month, and a correction pair booked there, count in that
    month; adjacent periods therefore add up to their union.
    """
    from app.services.own_transfers import confirmed_leg_ids
    from app.services.reconciliation import rows_settling_items

    effective = await effective_base_of(db, org_id)
    # Both legs of a transfer between the company's own accounts that a person confirmed are in no figure.
    transfer_legs = await confirmed_leg_ids(db, org_id)

    assumed = getattr(CanonicalTransaction, "currency_assumed", None)  # PR #110 adds it; use it when present
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
            CanonicalTransaction.corrects_id,
            CanonicalTransaction.asil_donem,
            *([assumed] if assumed is not None else []),
        ).where(
            CanonicalTransaction.org_id == org_id,
            CanonicalTransaction.ledger_status != EXCLUDED,
            *([CanonicalTransaction.id.not_in(transfer_legs)] if transfer_legs else []),
        ).order_by(CanonicalTransaction.transaction_date, CanonicalTransaction.id)
    )).all()
    settling = await rows_settling_items(db, org_id)
    # Correction rows (a closed-month category correction, `corrects_id` set) are not
    # money: the money views, the months and the counts read the real rows only.
    money = [r for r in rows if r.corrects_id is None]
    counted = [r for r in money if r.ledger_status != POSSIBLE_DUPLICATE]
    book_months = {month_of(r.transaction_date) for r in counted if r.basis == BOOK}
    cash_months = {month_of(r.transaction_date) for r in counted if r.basis == CASH}
    profit = [
        r for r in counted
        # The books already say what their month earned, and a settling line
        # is an invoice already counted, arriving.
        if (r.basis == BOOK or month_of(r.transaction_date) not in book_months)
        and not (r.basis == CASH and r.id in settling)
    ]
    # The by-category profit view also reads each correction pair, which moves an amount
    # between categories in an open month. The pair inherits the treatment of the row it
    # corrects: counted in profit only if that row is, whatever month the pair sits in.
    in_profit = {r.id for r in profit}
    corrections = [r for r in rows if r.corrects_id in in_profit and r.ledger_status != POSSIBLE_DUPLICATE]
    available = sorted({month_of(r.transaction_date) for r in counted})
    # The default period is anchored on money only (`counted` has no correction rows): a
    # pair booked after the last money month does not move the window, it is read when a
    # period reaches the month it is booked in.
    today = current_month()
    start, end, is_default = resolve_period(period, available, today)
    future = [r for r in counted if month_of(r.transaction_date) > today]

    def inside(r: Any) -> bool:
        return start is not None and end is not None and start <= month_of(r.transaction_date) <= end

    in_money = [r for r in money if inside(r)]
    in_counted = [r for r in counted if inside(r)]
    months = sorted({month_of(r.transaction_date) for r in in_counted})
    shown = LedgerPeriod(
        start=start, end=end, months=len(months),
        label=f"{start} – {end}" if start and end else None, is_default=is_default,
        available_start=available[0] if available else None,
        available_end=available[-1] if available else None, available_months=len(available),
        future_rows=len(future),
        future_latest=max((month_of(r.transaction_date) for r in future), default=None),
    )
    shown_profit = [r for r in profit + corrections if inside(r)]
    reclass = {
        r.id: r.asil_donem for r in shown_profit
        if r.corrects_id is not None and r.asil_donem and start and end
        and not start <= r.asil_donem <= end
    }
    return CompanyRows(
        profit=shown_profit,
        # A posting list with no bank statement beside it is the best view of cash.
        # A reclassification moves no cash: the pairs are not here.
        cash=[
            r for r in in_counted
            if r.basis == CASH or (r.basis == BOOK and month_of(r.transaction_date) not in cash_months)
        ],
        possible_duplicates=len(in_money) - len(in_counted),
        months=months,
        rows=len(in_counted),
        period=shown,
        reclass_of_period=reclass,
        base_currency=effective.run_currency or DEFAULT_BASE,
        effective=effective,
    )


async def ledger_summary(db: AsyncSession, org_id: str, period: Period | None = None) -> dict[str, Any]:
    """The company's figures from the ledger, in kuruş, for one period (default: last 12 months).

    The headline is decided by `effective_base`: the confirmed base currency; else the one currency
    the data holds (marked unconfirmed); else, with several and none confirmed, no headline at all:
    `currency` is None, the headline figures are 0 and `currency_totals` carries every currency side
    by side for the screen to show with the prompt to choose. Every currency other than the headline
    is summed on its own in `other_currencies` and never added to it (`core/currency_totals`).
    What awaits a person waits: open items are not a period's figures.
    """
    view = await company_rows(db, org_id, period)
    eb = view.effective
    headline = eb.currency
    cash, _ = split_by_currency(view.cash, headline) if headline else ([], {})
    profit, _ = split_by_currency(view.profit, headline) if headline else ([], {})
    months = {m: {"cash_in_cents": 0, "cash_out_cents": 0} for m in view.months}
    for r in cash:
        key = "cash_in_cents" if r.direction == "income" else "cash_out_cents"
        months[month_of(r.transaction_date)][key] += r.amount_cents
    earned = [r for r in profit if r.category not in BILANCO_KATEGORILERI]
    return {
        "last_upload": await _last_upload(db, org_id),
        "open_items": await _open_items_summary(db, org_id, view.base_currency),
        "rows": view.rows,
        "currency": headline,
        "base_state": eb.state,
        "base_confirmed": eb.confirmed,
        "confirm_path": eb.confirm_path,
        "revenue_cents": sum(r.amount_cents for r in earned if r.direction == "income"),
        "expense_cents": sum(r.amount_cents for r in earned if r.direction != "income"),
        "other_currencies": foreign_summaries(view.profit, view.cash, headline),
        "currency_totals": foreign_summaries(view.profit, view.cash, None),
        "possible_duplicates": view.possible_duplicates,
        "period": view.period.as_dict(),
        "months": [{"month": m, **months[m]} for m in view.months],
    }
