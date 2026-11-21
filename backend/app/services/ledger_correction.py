"""A category correction reaches the company ledger (plan v10 gap G3, step S1.5).

`canonical_transactions` is a projection of the analyses (plan v11 K1), and
`ledger.append_job` already rewrites a row's category in place when the same money is
read again. A correction does the same, at once, for the row with the same
`source_record_id`, in the caller's database transaction, so the `Transaction` and the
ledger cannot disagree.

**A closed month does not change** (services/donem_kilidi.py, owner's decision
2026-11-21). If the row belongs to a closed month it is left exactly as it is and the
correction is booked in the first open month as two rows linked to the original by
`source_record_id`: a reversal (the same money, negated, old category) and the corrected
row (the money, new category). The pair sums to zero change in totals and moves the
amount between categories; `asil_donem`/`asil_tarih` keep the closed period it belongs to.

Idempotent: a row's effective category is the original's, or the latest corrected row's;
asking for the category it already has writes nothing.

Audit: one `audit_logs` row per effective correction: who, when, old -> new, which ledger row.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.models.canonical_transaction import CanonicalTransaction
from app.models.transaction import Transaction
from app.models.user import User
from app.services.donem_kilidi import ilk_acik_donem, kilitli_donemler
from app.services.ledger import (
    SOURCE_CORRECTION,
    job_transactions,
    month_of,
    record_ids,
)


def _correction_ids(record_id: str, n: int) -> tuple[str, str]:
    return f"{record_id}~k{n}-iptal", f"{record_id}~k{n}-yeni"


async def apply_category_correction(
    db: AsyncSession, tx: Transaction, org_id: str | None, new_category: str, user: User,
) -> dict[str, Any]:
    """Carry `tx`'s new category into the ledger. Does not commit; the caller does.

    Call after `tx.category` was set (or pass the old value through the return). Returns
    what happened: `{"ledger": "none" | "updated" | "unchanged" | "booked_in_open_month", ...}`.
    """
    if not org_id:
        return {"ledger": "none"}
    org_id = str(org_id)
    usable, _ = record_ids(org_id, await job_transactions(db, tx.job_id))
    record_id = next((rid for rid, t in usable if t.id == tx.id), None)
    if record_id is None:
        return {"ledger": "none"}  # not counted by the ledger (no date, no amount)
    row = (await db.execute(select(CanonicalTransaction).where(
        CanonicalTransaction.org_id == org_id,
        CanonicalTransaction.source_record_id == record_id,
    ))).scalar_one_or_none()
    if row is None:
        return {"ledger": "none"}  # job not appended yet; the append reads the corrected row

    kilitli = await kilitli_donemler(db, org_id)
    if month_of(row.transaction_date) not in kilitli:
        old = row.category
        if old == new_category:
            return {"ledger": "unchanged", "source_record_id": record_id}
        row.category = new_category
        _audit(db, user, org_id, record_id, old, new_category, "updated", None)
        return {"ledger": "updated", "source_record_id": record_id}

    # Closed month: effective category is the latest corrected row's, else the original's.
    prior = [
        r for r in (await db.execute(
            select(CanonicalTransaction).where(
                CanonicalTransaction.org_id == org_id,
                CanonicalTransaction.source_type == SOURCE_CORRECTION,
                CanonicalTransaction.source_record_id.startswith(f"{record_id}~k", autoescape=True),
            )
        )).scalars()
        if r.source_record_id.endswith("-yeni")
    ]
    latest = max(prior, key=lambda r: int(r.source_record_id.rsplit("~k", 1)[1].split("-")[0]), default=None)
    effective = latest.category if latest is not None else row.category
    if effective == new_category:
        return {"ledger": "unchanged", "source_record_id": record_id}
    n = len(prior) + 1
    iptal_id, yeni_id = _correction_ids(record_id, n)
    donem = row.asil_donem or month_of(row.transaction_date)
    hedef = ilk_acik_donem(donem, kilitli)
    common: dict[str, Any] = {
        "org_id": org_id, "source_type": SOURCE_CORRECTION, "source_job_id": row.source_job_id,
        "transaction_date": datetime(int(hedef[:4]), int(hedef[5:7]), 1, tzinfo=UTC),
        "asil_tarih": row.asil_tarih or row.transaction_date, "asil_donem": donem,
        "currency": row.currency, "direction": row.direction, "account_code": row.account_code,
        "counterparty": row.counterparty, "description": row.description, "confidence": row.confidence,
        "ledger_status": row.ledger_status, "basis": row.basis,
    }
    db.add(CanonicalTransaction(
        id=str(uuid.uuid4()), source_record_id=iptal_id, amount_cents=-row.amount_cents,
        category=effective, **common,
    ))
    db.add(CanonicalTransaction(
        id=str(uuid.uuid4()), source_record_id=yeni_id, amount_cents=row.amount_cents,
        category=new_category, **common,
    ))
    _audit(db, user, org_id, record_id, effective, new_category, "booked_in_open_month", hedef)
    return {"ledger": "booked_in_open_month", "source_record_id": record_id, "donem": hedef}


def _audit(
    db: AsyncSession, user: User, org_id: str, record_id: str, old: str | None, new: str,
    how: str, booked_in: str | None,
) -> None:
    db.add(AuditLog(
        user_id=str(user.id), user_email=getattr(user, "email", None),
        action="ledger.category_correction", resource=f"canonical_transactions/{record_id}",
        request_body={"org_id": org_id, "source_record_id": record_id, "old": old, "new": new,
                      "mode": how, "booked_in": booked_in},
        response_status=200,
    ))
