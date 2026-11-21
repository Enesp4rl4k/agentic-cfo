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
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dates import parse_transaction_date
from app.core.row_confidence import label, parse_confidence
from app.core.turkish import fold
from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.decision import DecidedVia, DecisionKind
from app.models.held_transaction import PENDING, REJECTED, RELEASED, HeldTransaction
from app.services.decisions import record_decision
from app.services.ingest.persist import build_transaction

# What a person reads, per reason code (app.services.ingest.hold).
REASON_TEXT: dict[str, str] = {
    "confidence_unknown": "güven bilinmiyor",
    "confidence_low": "güven düşük",
    "currency_unknown": "para birimi bilinmiyor",
    "direction_unknown": "yön belirsiz",
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


def _apply_corrections(payload: dict[str, Any], corrections: dict[str, Any] | None) -> dict[str, Any]:
    out = dict(payload)
    for key, value in (corrections or {}).items():
        if key not in _CORRECTABLE or value is None or value == "":
            continue
        if key == "type" and value not in ("income", "expense"):
            raise CorrectionError("type must be income or expense")
        if key == "currency":
            value = str(value).strip().upper()
            if not (len(value) == 3 and value.isalpha()):
                raise CorrectionError("currency must be an ISO-4217 code")
        if key == "amount_cents" and (isinstance(value, bool) or not isinstance(value, int) or value == 0):
            raise CorrectionError("amount_cents must be a non-zero integer")
        if key == "transaction_date":
            if parse_transaction_date(str(value))[1]:
                raise CorrectionError("transaction_date must be a readable date (YYYY-MM-DD)")
            value = str(value)
        out[key] = value
    if out.get("hold_reasons"):
        fixed = {
            "type": "direction_unknown", "currency": "currency_unknown",
            "transaction_date": "date_unreadable", "amount_cents": "amount_unreadable",
        }
        gone = {fixed[k] for k in (corrections or {}) if k in fixed and (corrections or {}).get(k) not in (None, "")}
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
        "type": payload.get("type"),
        "transaction_date": payload.get("transaction_date"),
        "hold_reasons": list(payload.get("hold_reasons") or []),
    }


async def resolve(
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
) -> dict[str, Any]:
    """Release or reject pending rows of an organisation. One transaction; commits.

    Rows are picked by `ids`, or by `job_id` / `reason` / `document_id`. `corrections`
    maps a row id to the fields a person fixed (type, currency, transaction_date,
    amount_cents); `currency` fills the currency of every picked row that has none.
    A document is released or rejected whole: if any of its rows cannot be released
    (something still missing), none is.
    """
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
        payload = _apply_corrections(row.payload, fix)
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
    await db.commit()
    appended: dict[str, Any] = {}
    for jid in sorted(jobs):
        job = await db.get(AnalysisJob, jid)
        if job is not None and job.org_id and job.status == JobStatus.COMPLETED:
            from app.services.ledger import append_job

            appended[jid] = await append_job(db, jid)
    return {
        "resolved": resolved,
        "blocked": [{"id": i, "missing": m} for i, m in blocked.items()],
        "already_resolved": already,
        "still_waiting": await pending_count(db, org_id),
        "ledger": appended,
    }


async def fill_currency(
    db: AsyncSession, org_id: str, user_id: str, code: str
) -> dict[str, Any]:
    """The company currency was just confirmed: apply it to rows held for that and nothing else.

    A row whose only open question was the currency is released; a row with
    another question keeps waiting, with its currency now filled and marked
    assumed. Commits.
    """
    only_currency: list[str] = []
    for row in await pending_rows(db, org_id, reason=CURRENCY_REASON):
        payload = dict(row.payload)
        reasons = [r for r in payload.get("hold_reasons", []) if r != CURRENCY_REASON]
        payload.update(currency=code, currency_assumed=True, hold_reasons=reasons)
        await db.execute(
            update(HeldTransaction).where(HeldTransaction.id == row.id, HeldTransaction.status == PENDING)
            .values(payload=payload).execution_options(synchronize_session=False)
        )
        if not reasons:
            only_currency.append(row.id)
    await db.commit()
    if not only_currency:
        return {"resolved": 0, "blocked": [], "already_resolved": 0,
                "still_waiting": await pending_count(db, org_id), "ledger": {}}
    return await resolve(
        db, org_id, user_id=user_id, release=True, ids=only_currency,
        note="company currency confirmed",
    )
