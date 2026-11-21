"""Rows waiting for a person: hold them once, list them, release (as is or corrected) or reject them.

Releasing is the human's answer to "I was not sure": the row becomes a
`Transaction` of its job and, when the job is complete, joins the company ledger
through the ledger's own idempotent append. Every answer is a recorded decision
(`services/decisions.py`, in the same transaction), not just a timestamp.

A question is asked once. A row has a stable identity (`row_key`: its content, not
its job), so a re-upload of the same file or a rerun of the same job neither
creates a second pending row nor re-asks a row already released or rejected.
Resolution is a compare-and-set on `status = 'pending'`: two clicks on one row
resolve it once.

Rows of one document are resolved together, as they were held together.
"""
from __future__ import annotations

import hashlib
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.currencies import is_currency_code
from app.core.dates import parse_transaction_date
from app.core.row_confidence import label, parse_confidence
from app.core.turkish import fold
from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.decision import DecidedVia, DecisionKind
from app.models.held_transaction import PENDING, REJECTED, RELEASED, HeldTransaction
from app.services.decisions import record_decision
from app.services.ingest.hold import (
    AMOUNT_UNREADABLE,
    AMOUNT_ZERO,
    BALANCE_MISMATCH,
    CURRENCY_UNKNOWN,
    DATE_UNREADABLE,
    DIRECTION_FILE,
    DIRECTION_UNKNOWN,
    row_reasons,
)
from app.services.ingest.persist import build_transaction

# What a person reads, per reason code (app.services.ingest.hold).
REASON_TEXT: dict[str, str] = {
    "confidence_unknown": "güven bilinmiyor",
    "confidence_low": "güven düşük",
    "currency_unknown": "para birimi bilinmiyor",
    "direction_unknown": "yön belirsiz",
    "direction_file_unknown": "yön belirsiz",
    "balance_mismatch": "bakiye ile uyuşmuyor",
    "summary_suspect": "özet satırı olabilir",
    "amount_zero": "tutar sıfır",
    "malformed_row": "sütunlar kaymış olabilir",
    "amount_unreadable": "tutar okunamadı",
    "date_unreadable": "tarih okunamadı",
    "document_held_together": "aynı belgenin başka bir satırı bekliyor",
}
CURRENCY_REASON = "currency_unknown"
_CORRECTABLE = ("type", "currency", "transaction_date", "amount_cents")


# ── identity ─────────────────────────────────────────────────────────────────

def row_key(org_id: str | None, row: dict[str, Any], occurrence: int = 1) -> str:
    """The identity of an extracted row: what it says, not which job read it.

    Currency and confidence are left out (a later confirmation changes them, and
    they are what is being asked); `occurrence` tells two identical rows of one
    file apart, so the same file again gives the same keys.
    """
    if row.get("document_id"):
        material = ["doc", str(row["document_id"]), str(row.get("amount_cents")), str(row.get("type"))]
    else:
        material = [
            "row", str(row.get("transaction_date")), str(row.get("amount_cents")), str(row.get("type")),
            fold(str(row.get("description") or row.get("vendor") or "")),
        ]
    material.insert(0, org_id or "")
    material.append(str(occurrence))
    return hashlib.sha256("|".join(material).encode()).hexdigest()


# ── hold stage (worker) ──────────────────────────────────────────────────────

async def register_held(
    db: AsyncSession, job_id: str, org_id: str | None, rows: list[dict[str, Any]]
) -> dict[str, Any]:
    """Store newly held rows once; return what was already answered or already waiting.

    `released_again` are rows a person already released: the caller keeps them in
    this job's transactions (the answer stands); rejected ones are not re-asked.
    """
    seen: Counter[str] = Counter()
    keyed: list[tuple[str, dict[str, Any]]] = []
    for row in rows:
        base = row_key(org_id, row, 1)
        seen[base] += 1
        keyed.append((row_key(org_id, row, seen[base]), row))
    known: dict[str, HeldTransaction] = {}
    if keyed:
        found = (await db.execute(
            select(HeldTransaction).where(
                HeldTransaction.org_id == org_id if org_id else HeldTransaction.org_id.is_(None),
                HeldTransaction.row_key.in_([k for k, _ in keyed]),
            ).order_by(HeldTransaction.created_at)
        )).scalars().all()
        for h in found:
            known[h.row_key] = h   # the latest answer for a key
    out: dict[str, Any] = {
        "new": 0, "already_waiting": 0, "already_rejected": 0, "released_again": [], "currency_unknown": 0,
    }
    for key, row in keyed:
        prior = known.get(key)
        if prior is None:
            db.add(HeldTransaction(job_id=job_id, org_id=org_id, row_key=key, payload=row))
            out["new"] += 1
            if CURRENCY_REASON in (row.get("hold_reasons") or []):
                out["currency_unknown"] += 1
        elif prior.status == RELEASED:
            out["released_again"].append(dict(prior.payload))
        elif prior.status == REJECTED:
            out["already_rejected"] += 1
        else:
            out["already_waiting"] += 1
    return out


# ── reading ──────────────────────────────────────────────────────────────────

async def pending_rows(
    db: AsyncSession, org_id: str, *, job_id: str | None = None, reason: str | None = None,
    document_id: str | None = None,
) -> list[HeldTransaction]:
    stmt = select(HeldTransaction).where(HeldTransaction.org_id == org_id, HeldTransaction.status == PENDING)
    if job_id:
        stmt = stmt.where(HeldTransaction.job_id == job_id)
    # populate_existing: payloads are rewritten by UPDATE statements, so a cached object may be stale.
    ordered = stmt.order_by(HeldTransaction.created_at, HeldTransaction.id).execution_options(populate_existing=True)
    rows = list((await db.execute(ordered)).scalars().all())
    if reason:
        rows = [r for r in rows if reason in (r.payload.get("hold_reasons") or [])]
    if document_id:
        rows = [r for r in rows if r.payload.get("document_id") == document_id]
    return rows


async def pending_count(db: AsyncSession, org_id: str, job_id: str | None = None) -> int:
    stmt = select(func.count()).select_from(HeldTransaction).where(
        HeldTransaction.org_id == org_id, HeldTransaction.status == PENDING
    )
    if job_id:
        stmt = stmt.where(HeldTransaction.job_id == job_id)
    return int((await db.execute(stmt)).scalar() or 0)


async def held_note(db: AsyncSession, org_id: str) -> str:
    """The sentence the Monday briefing appends when rows wait; "" when none do."""
    waiting = await pending_count(db, org_id)
    return f" Not: {waiting} kayıt incelemenizi bekliyor; bu rakamlara dahil değil." if waiting else ""


def describe(row: HeldTransaction, filename: str | None = None) -> dict[str, Any]:
    p = row.payload
    confidence = parse_confidence(p.get("confidence"))
    reasons = list(p.get("hold_reasons") or [])
    return {
        "id": row.id,
        "job_id": row.job_id,
        "source": {"job_id": row.job_id, "filename": filename, "document_id": p.get("document_id")},
        "reasons": reasons,
        "reason_labels": [REASON_TEXT.get(r, r) for r in reasons],
        "confidence": confidence,                       # None = unknown; never a made-up number
        "confidence_label": label(confidence),
        "amount_cents": p.get("amount_cents"),
        "currency": p.get("currency"),
        "type": p.get("type"),
        "currency_assumed": bool(p.get("currency_assumed")),
        "direction_file": (p.get("direction_file") or {}).get("key"),
        "description": p.get("description"),
        "vendor": p.get("vendor"),
        "transaction_date": p.get("transaction_date"),
        "document_id": p.get("document_id"),
    }


async def list_pending(db: AsyncSession, org_id: str, job_id: str | None = None) -> list[dict[str, Any]]:
    rows = await pending_rows(db, org_id, job_id=job_id)
    names: dict[str, str] = {}
    if rows:
        found = await db.execute(
            select(AnalysisJob.id, AnalysisJob.filename).where(AnalysisJob.id.in_({r.job_id for r in rows}))
        )
        names = dict(found.all())  # type: ignore[arg-type]
    return [describe(r, names.get(r.job_id)) for r in rows]


# ── resolving ────────────────────────────────────────────────────────────────

class CorrectionError(ValueError):
    """A correction is not usable; nothing was written."""


class UnknownRows(LookupError):
    """Row ids that are not this organisation's (or do not exist): the caller answers 404."""


# Which open question each corrected field answers.
_FIXES = {
    "type": (DIRECTION_UNKNOWN, DIRECTION_FILE, BALANCE_MISMATCH),
    "currency": (CURRENCY_UNKNOWN,),
    "transaction_date": (DATE_UNREADABLE,),
    "amount_cents": (AMOUNT_UNREADABLE, AMOUNT_ZERO),
}
_EARLIEST = date(2000, 1, 1)
_LATEST_AHEAD = timedelta(days=366)


def _valid_date(value: Any) -> str:
    parsed, estimated = parse_transaction_date(str(value))
    if estimated:
        raise CorrectionError("transaction_date must be a readable date (YYYY-MM-DD)")
    if not (_EARLIEST <= parsed.date() <= datetime.now(UTC).date() + _LATEST_AHEAD):
        raise CorrectionError("transaction_date is outside the plausible range (2000 to a year ahead)")
    return str(value)


def apply_corrections(payload: dict[str, Any], corrections: dict[str, Any] | None) -> dict[str, Any]:
    """The row with a person's fixes applied. Every fix is checked; one bad one writes nothing."""
    out = dict(payload)
    fixed: set[str] = set()
    for key, value in (corrections or {}).items():
        if key not in _CORRECTABLE or value is None or value == "":
            continue
        if key == "type" and value not in ("income", "expense"):
            raise CorrectionError("type must be income or expense")
        if key == "currency":
            value = str(value).strip().upper()
            if not is_currency_code(value):
                raise CorrectionError("currency must be a known ISO-4217 code")
            out.pop("currency_assumed", None)   # a person said it: it is no longer assumed
        if key == "amount_cents":
            # The direction is its own field: an amount is a magnitude.
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise CorrectionError("amount_cents must be a positive integer (the direction is the type)")
        if key == "transaction_date":
            value = _valid_date(value)
        out[key] = value
        fixed.add(key)
    if "amount_cents" in fixed:
        out.pop("zero_amount", None)
    if "type" in fixed:
        out.pop("direction_file", None)
        out.pop("direction_question", None)
        out.pop("balance_mismatch", None)
        if out.get("category") is None:        # chosen now that the direction is known
            from app.services.ingest.rows import _yukleyenin_kategorisi

            out["category"] = _yukleyenin_kategorisi(
                str(out.get("category_hint") or ""), str(out.get("description") or ""), out["type"]
            )
    if out.get("hold_reasons"):
        gone = {reason for k in fixed for reason in _FIXES[k]}
        out["hold_reasons"] = [r for r in out["hold_reasons"] if r not in gone]
    return out


def _missing(payload: dict[str, Any]) -> list[str]:
    """What a row still lacks to be booked: a correction must supply it."""
    lacking: list[str] = []
    if not str(payload.get("currency") or "").strip():
        lacking.append("currency")
    if payload.get("type") not in ("income", "expense"):
        lacking.append("type")
    if not payload.get("amount_cents"):
        lacking.append("amount_cents")
    if parse_transaction_date(payload.get("transaction_date"))[1]:
        lacking.append("transaction_date")
    return lacking


def _snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    amount = payload.get("amount_cents")
    return {
        "amount_cents": amount if isinstance(amount, int) and not isinstance(amount, bool) else None,
        "currency": payload.get("currency"),
        "currency_assumed": bool(payload.get("currency_assumed")),
        "type": payload.get("type"),
        "transaction_date": payload.get("transaction_date"),
        "hold_reasons": list(payload.get("hold_reasons") or []),
    }


async def _check_ids(db: AsyncSession, org_id: str, ids: list[str]) -> None:
    """Every id must be a row of this organisation, whatever its status; else nothing is touched."""
    if not ids:
        return
    own = set((await db.execute(
        select(HeldTransaction.id).where(HeldTransaction.org_id == org_id, HeldTransaction.id.in_(set(ids)))
    )).scalars().all())
    if unknown := sorted(set(ids) - own):
        raise UnknownRows(", ".join(unknown))


async def update_waiting(
    db: AsyncSession, org_id: str, user_id: str, payloads: dict[str, dict[str, Any]], note: str,
) -> int:
    """Store a person's answer on rows that stay pending (another question is still open). No commit.

    Each one is a recorded decision with before and after, like a release: an answer that changes
    a row is never silent just because the row keeps waiting.
    """
    changed = 0
    for row in await pending_rows(db, org_id):
        if row.id not in payloads:
            continue
        new = payloads[row.id]
        new["hold_reasons"] = row_reasons(new)
        won = await db.execute(
            update(HeldTransaction).where(HeldTransaction.id == row.id, HeldTransaction.status == PENDING)
            .values(payload=new).execution_options(synchronize_session=False)
        )
        if won.rowcount != 1:
            continue
        await record_decision(
            db, org_id=org_id, kind=DecisionKind.HELD_ROW_RESOLUTION, target_type="held_transaction",
            target_id=row.id, outcome="updated", decided_via=DecidedVia.HUMAN, decided_by=user_id, reason=note,
            evidence_refs=[{"type": "analysis_job", "id": row.job_id}],
            before=_snapshot(row.payload), after=_snapshot(new),
        )
        changed += 1
    return changed


async def resolve_uncommitted(
    db: AsyncSession,
    org_id: str,
    *,
    user_id: str,
    release: bool,
    ids: list[str] | None = None,
    job_id: str | None = None,
    reason: str | None = None,
    document_id: str | None = None,
    corrections: dict[str, dict[str, Any]] | None = None,
    currency: str | None = None,
    note: str | None = None,
    staged: dict[str, dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], set[str]]:
    """`resolve` without the commit: (result, the jobs whose rows were released)."""
    await _check_ids(db, org_id, [*(ids or []), *(corrections or {})])
    picked = await pending_rows(db, org_id, job_id=job_id, reason=reason, document_id=document_id)
    if ids is not None:
        wanted = set(ids)
        picked = [r for r in picked if r.id in wanted]
    # A document moves as one.
    documents = {(r.job_id, r.payload.get("document_id")) for r in picked if r.payload.get("document_id")}
    if documents:
        have = {r.id for r in picked}
        for r in await pending_rows(db, org_id):
            if (r.job_id, r.payload.get("document_id")) in documents and r.id not in have:
                picked.append(r)
    corrections = corrections or {}
    final: dict[str, dict[str, Any]] = {}
    blocked: dict[str, list[str]] = {}
    for row in picked:
        fix = dict(corrections.get(row.id) or {})
        if currency and not str(row.payload.get("currency") or "").strip():
            fix.setdefault("currency", currency)
        # `staged` is what the row becomes before the person's fixes (a confirmed currency, say);
        # the decision still records the row as it was.
        payload = apply_corrections((staged or {}).get(row.id, row.payload), fix)
        final[row.id] = payload
        if release and (lacking := _missing(payload)):
            blocked[row.id] = lacking
    if release:
        for r in picked:
            key = (r.job_id, r.payload.get("document_id"))
            if r.payload.get("document_id") and r.id not in blocked and any(
                (o.job_id, o.payload.get("document_id")) == key and o.id in blocked for o in picked
            ):
                blocked[r.id] = ["document"]
    now = datetime.now(UTC)
    resolved = 0
    already = 0
    jobs: set[str] = set()
    for row in picked:
        if row.id in blocked:
            continue
        payload = final[row.id]
        status = RELEASED if release else REJECTED
        won = await db.execute(
            update(HeldTransaction)
            .where(HeldTransaction.id == row.id, HeldTransaction.status == PENDING)
            .values(status=status, resolved_at=now, resolved_by=user_id, payload=payload)
            .execution_options(synchronize_session=False)
        )
        if won.rowcount != 1:       # someone else resolved it first
            already += 1
            continue
        corrected = release and _snapshot(payload) != _snapshot(row.payload)
        if release:
            db.add(build_transaction(row.job_id, payload))
            jobs.add(row.job_id)
        await record_decision(
            db,
            org_id=org_id,
            kind=DecisionKind.HELD_ROW_RESOLUTION,
            target_type="held_transaction",
            target_id=row.id,
            outcome=("corrected_released" if corrected else "released") if release else "rejected",
            decided_via=DecidedVia.HUMAN,
            decided_by=user_id,
            reason=note,
            evidence_refs=[{"type": "analysis_job", "id": row.job_id}],
            before=_snapshot(row.payload),
            after=_snapshot(payload) if release else None,
        )
        resolved += 1
    return {
        "resolved": resolved,
        "blocked": [{"id": i, "missing": m} for i, m in blocked.items()],
        "already_resolved": already,
    }, jobs


async def append_released(db: AsyncSession, jobs: set[str]) -> dict[str, Any]:
    """After the commit: add the jobs whose rows were released to the ledger (idempotent)."""
    appended: dict[str, Any] = {}
    for jid in sorted(jobs):
        job = await db.get(AnalysisJob, jid)
        if job is not None and job.org_id and job.status == JobStatus.COMPLETED:
            from app.services.ledger import append_job

            appended[jid] = await append_job(db, jid)
    return appended


async def resolve(db: AsyncSession, org_id: str, **kwargs: Any) -> dict[str, Any]:
    """Release or reject pending rows of an organisation. One transaction; commits.

    Rows are picked by `ids`, or by `job_id` / `reason` / `document_id`. `corrections`
    maps a row id to the fields a person fixed (type, currency, transaction_date,
    amount_cents); `currency` fills the currency of every picked row that has none.
    A document is released or rejected whole: if any of its rows cannot be released
    (something still missing), none is. An id that is not this organisation's raises
    `UnknownRows` before anything is written.
    """
    out, jobs = await resolve_uncommitted(db, org_id, **kwargs)
    await db.commit()
    out["still_waiting"] = await pending_count(db, org_id)
    out["ledger"] = await append_released(db, jobs)
    return out


async def fill_currency(
    db: AsyncSession, org_id: str, user_id: str, code: str
) -> tuple[dict[str, Any], set[str]]:
    """The company currency is being confirmed: apply it to rows held for that and nothing else.

    No commit: the caller confirms the currency, fills the rows and releases them in ONE
    transaction, then adds the jobs to the ledger. A row whose only open question was the
    currency is released; a row with another question keeps waiting, with its currency now
    filled and marked assumed, and that change is a recorded decision.
    """
    only_currency: list[str] = []
    staged: dict[str, dict[str, Any]] = {}
    waiting: dict[str, dict[str, Any]] = {}
    for row in await pending_rows(db, org_id, reason=CURRENCY_REASON):
        payload = dict(row.payload)
        reasons = [r for r in payload.get("hold_reasons", []) if r != CURRENCY_REASON]
        payload.update(currency=code, currency_assumed=True, hold_reasons=reasons)
        if reasons:
            waiting[row.id] = payload
        else:
            only_currency.append(row.id)
            staged[row.id] = payload
    await update_waiting(db, org_id, user_id, waiting, "company currency confirmed")
    out, jobs = await resolve_uncommitted(
        db, org_id, user_id=user_id, release=True, ids=only_currency, staged=staged,
        note="company currency confirmed",
    ) if only_currency else ({"resolved": 0, "blocked": [], "already_resolved": 0}, set())
    out["still_waiting"] = await pending_count(db, org_id)
    return out, jobs


async def assumed_under_other_currency(db: AsyncSession, org_id: str, code: str) -> dict[str, Any]:
    """Rows booked in a currency the document did not state, whose currency is not `code`.

    When the company currency is confirmed anew, rows previously admitted as `currency_assumed`
    keep the currency they were stored with: nothing is rewritten silently. They are listed here
    so a person can review them (and correct a row's currency by hand).
    """
    from app.models.transaction import Transaction

    rows = (await db.execute(
        select(Transaction.id, Transaction.currency)
        .join(AnalysisJob, AnalysisJob.id == Transaction.job_id)
        .where(AnalysisJob.org_id == org_id, Transaction.currency_assumed.is_(True), Transaction.currency != code)
        .order_by(Transaction.id)
    )).all()
    return {
        "count": len(rows),
        "by_currency": dict(Counter(c for _, c in rows)),
        "transaction_ids": [i for i, _ in rows[:100]],
    }
