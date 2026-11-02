"""The company ledger: what it holds, and the rows waiting for a person."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.access import ensure_tenant
from app.api.auth import get_current_user
from app.database import get_db
from app.models.canonical_transaction import CanonicalTransaction
from app.models.user import User
from app.services.ledger import ACTIVE, EXCLUDED, POSSIBLE_DUPLICATE, ledger_summary

router = APIRouter()


class ResolveRequest(BaseModel):
    action: Literal["keep", "exclude"]


def _org(user: User) -> str:
    if not user.org_id:
        raise HTTPException(400, "Bu işlem için bir organizasyon gerekli.")
    return str(user.org_id)


def _row(r: CanonicalTransaction) -> dict[str, Any]:
    return {
        "id": r.id,
        "transaction_date": r.transaction_date.isoformat()[:10],
        "amount_cents": r.amount_cents,
        "direction": r.direction,
        "description": r.description,
        "category": r.category,
        "source_job_id": r.source_job_id,
    }


@router.get("/ledger/summary", responses={400: {"description": "The user has no organisation."}})
async def get_summary(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return {"data": await ledger_summary(db, _org(user)), "error": None}


@router.get("/ledger/possible-duplicates", responses={400: {"description": "The user has no organisation."}})
async def get_possible_duplicates(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Rows that may repeat money already in the ledger, with what they may repeat."""
    org_id = _org(user)
    rows = (await db.execute(
        select(CanonicalTransaction)
        .where(CanonicalTransaction.org_id == org_id, CanonicalTransaction.ledger_status == POSSIBLE_DUPLICATE)
        .order_by(CanonicalTransaction.transaction_date)
    )).scalars().all()
    data = []
    for row in rows:
        match = await db.get(CanonicalTransaction, row.duplicate_of) if row.duplicate_of else None
        data.append({**_row(row), "matches": [_row(match)] if match and match.org_id == org_id else []})
    return {"data": data, "error": None}


@router.post(
    "/ledger/rows/{row_id}/resolve",
    responses={
        400: {"description": "The user has no organisation."},
        404: {"description": "No such row in this organisation."},
        409: {"description": "The row is not waiting for a decision."},
    },
)
async def resolve_possible_duplicate(
    row_id: str,
    body: ResolveRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """A person's call: it is separate money (keep), or the same money (exclude).

    An excluded row stays on record; it just is not counted.
    """
    _org(user)
    row = await db.get(CanonicalTransaction, row_id)
    if row is None:
        raise HTTPException(404, "Kayıt bulunamadı.")
    ensure_tenant(user, org_id=row.org_id)
    won = await db.execute(
        update(CanonicalTransaction)
        .where(CanonicalTransaction.id == row_id, CanonicalTransaction.ledger_status == POSSIBLE_DUPLICATE)
        .values(ledger_status=ACTIVE if body.action == "keep" else EXCLUDED)
        .execution_options(synchronize_session=False)
    )
    await db.commit()
    if won.rowcount != 1:
        raise HTTPException(409, "Bu kayıt karar beklemiyor.")
    return {"data": {"id": row_id, "action": body.action}, "error": None}
