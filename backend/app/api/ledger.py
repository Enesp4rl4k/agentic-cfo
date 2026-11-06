"""The company ledger: what it holds, and the rows waiting for a person."""
from __future__ import annotations

from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.access import ensure_tenant
from app.api.auth import get_current_user
from app.database import get_db
from app.models.canonical_transaction import CanonicalTransaction
from app.models.open_item import OpenItem
from app.models.open_item_match import OpenItemMatch
from app.models.user import User
from app.services.cash_radar import compute_cash_radar
from app.services.ledger import ACTIVE, EXCLUDED, POSSIBLE_DUPLICATE, ledger_summary
from app.services.reconciliation import (
    CONFIRMED,
    PROPOSED,
    REJECTED,
    apply_payment,
    payment_behaviour,
)

router = APIRouter()


class ResolveRequest(BaseModel):
    action: Literal["keep", "exclude"]


class SettlementRequest(BaseModel):
    action: Literal["confirm", "reject"]


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


@router.get("/ledger/open-items", responses={400: {"description": "The user has no organisation."}})
async def get_open_items(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """What this company is owed and owes, soonest due first; undated last."""
    rows = (await db.execute(
        select(OpenItem)
        .where(OpenItem.org_id == _org(user), OpenItem.status == "open")
        .order_by(OpenItem.due_date.is_(None), OpenItem.due_date, OpenItem.issue_date)
    )).scalars()
    return {
        "data": [
            {
                "id": i.id,
                "direction": i.direction,
                "counterparty": i.counterparty,
                "description": i.description,
                "amount_cents": i.amount_cents,
                "currency": i.currency,
                "issue_date": i.issue_date.isoformat(),
                "due_date": i.due_date.isoformat() if i.due_date else None,
                "payment_note": i.payment_note,
            }
            for i in rows
        ],
        "error": None,
    }


@router.get("/ledger/settlements/proposed", responses={400: {"description": "The user has no organisation."}})
async def get_proposed_settlements(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Bank movements that may pay an invoice, waiting for a person."""
    org_id = _org(user)
    matches = (await db.execute(
        select(OpenItemMatch)
        .where(OpenItemMatch.org_id == org_id, OpenItemMatch.status == PROPOSED)
        .order_by(OpenItemMatch.matched_on)
    )).scalars().all()
    data = []
    for m in matches:
        item = await db.get(OpenItem, m.open_item_id)
        row = await db.get(CanonicalTransaction, m.ledger_row_id)
        if item is None or row is None:
            continue
        data.append({
            "id": m.id,
            "amount_cents": m.amount_cents,
            "method": m.method,
            "row": _row(row),
            "item": {
                "counterparty": item.counterparty,
                "description": item.description,
                "amount_cents": item.amount_cents,
                "paid_cents": item.paid_cents,
                "due_date": item.due_date.isoformat() if item.due_date else None,
            },
        })
    return {"data": data, "error": None}


def _refresh_view(org_id: str) -> None:
    """A decision changes what the ledger counts, so the company's view follows."""
    from app.core.background import spawn
    from app.worker import refresh_company_view_detached

    spawn(refresh_company_view_detached(org_id), name=f"ledger-view-{org_id[:8]}")


@router.post(
    "/ledger/settlements/{match_id}/resolve",
    responses={
        400: {"description": "The user has no organisation."},
        404: {"description": "No such proposal in this organisation."},
        409: {"description": "Already decided."},
    },
)
async def resolve_settlement(
    match_id: str,
    body: SettlementRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """A person's call. "Reject" is remembered: the line counts as its own money."""
    _org(user)
    match = await db.get(OpenItemMatch, match_id)
    if match is None:
        raise HTTPException(404, "Kayıt bulunamadı.")
    ensure_tenant(user, org_id=match.org_id)
    org_id = str(match.org_id)   # the commit below expires the row
    won = await db.execute(
        update(OpenItemMatch)
        .where(OpenItemMatch.id == match_id, OpenItemMatch.status == PROPOSED)
        .values(status=CONFIRMED if body.action == "confirm" else REJECTED, decided_by=str(user.id))
        .execution_options(synchronize_session=False)
    )
    if won.rowcount != 1:
        await db.rollback()
        raise HTTPException(409, "Bu öneri karar beklemiyor.")
    if body.action == "confirm":
        item = await db.get(OpenItem, match.open_item_id)
        if item is not None:
            apply_payment(item, match.amount_cents)
    await db.commit()
    _refresh_view(org_id)
    return {"data": {"id": match_id, "action": body.action}, "error": None}


@router.get("/ledger/payment-behaviour", responses={400: {"description": "The user has no organisation."}})
async def get_payment_behaviour(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """How late each counterparty really settles, from matched bank movements."""
    return {"data": await payment_behaviour(db, _org(user)), "error": None}


@router.get("/ledger/cash-radar", responses={400: {"description": "The user has no organisation or invalid date."}})
async def get_cash_radar(
    anchor_date: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """The next 13 weeks of open invoices against the last proven bank balance."""
    parsed_anchor: date | None = None
    if anchor_date:
        try:
            parsed_anchor = date.fromisoformat(anchor_date)
        except ValueError:
            raise HTTPException(400, "Geçersiz tarih biçimi (YYYY-AA-GG bekleniyor).") from None
    result = await compute_cash_radar(db, _org(user), anchor_date=parsed_anchor)
    return {"data": result.to_dict(), "error": None}


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
    org_id = str(row.org_id)   # the commit below expires the row
    won = await db.execute(
        update(CanonicalTransaction)
        .where(CanonicalTransaction.id == row_id, CanonicalTransaction.ledger_status == POSSIBLE_DUPLICATE)
        .values(ledger_status=ACTIVE if body.action == "keep" else EXCLUDED)
        .execution_options(synchronize_session=False)
    )
    await db.commit()
    if won.rowcount != 1:
        raise HTTPException(409, "Bu kayıt karar beklemiyor.")
    _refresh_view(org_id)
    return {"data": {"id": row_id, "action": body.action}, "error": None}
