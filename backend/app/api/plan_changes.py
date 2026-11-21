"""Payment plan changes: a member proposes, an owner or an admin decides.

POST /ledger/plan-changes                       propose a new date for a payable
GET  /ledger/plan-changes?status=pending        the proposals of the caller's organisation
POST /ledger/plan-changes/{change_id}/approve   owner or admin
POST /ledger/plan-changes/{change_id}/reject    owner or admin, with a reason
POST /ledger/plan-changes/{change_id}/withdraw  the proposer, while it waits

The rule and its reasons are in app/services/payment_plan.py and docs/payment-plan-approval.md.
Every route is scoped to the caller's organisation: another organisation's proposal is a 404.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.access import ensure_tenant
from app.api.auth import get_current_user
from app.api.contract import Envelope
from app.database import get_db
from app.models.open_item import OpenItem
from app.models.payment_plan_change import STATUSES, PaymentPlanChange
from app.models.user import User
from app.services import payment_plan
from app.services.acting_role import acting_role
from app.services.payment_plan import PlanChangeError

router = APIRouter()


class ProposeRequest(BaseModel):
    open_item_id: str
    to_date: date
    note: str | None = Field(default=None, max_length=1000)


class DecisionRequest(BaseModel):
    note: str | None = Field(default=None, max_length=1000)


class PlanChangeView(BaseModel):
    id: str
    open_item_id: str
    counterparty: str | None
    description: str | None
    amount_cents: int | None
    from_date: str
    to_date: str
    status: str
    requested_by: str
    requested_at: str
    request_note: str | None
    decided_by: str | None
    decided_at: str | None
    decision_note: str | None


class PlanChangeListMeta(BaseModel):
    can_decide: bool


class PlanChangeList(Envelope[list[PlanChangeView]]):
    meta: PlanChangeListMeta  # type: ignore[assignment]  # narrows the envelope's free-form meta


def _org(user: User) -> str:
    if not user.org_id:
        raise HTTPException(400, "Bu işlem için bir organizasyon gerekli.")
    return str(user.org_id)


def _fail(exc: PlanChangeError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=exc.message)


def _view(change: PaymentPlanChange, item: OpenItem | None) -> dict[str, Any]:
    return {
        "id": change.id,
        "open_item_id": change.open_item_id,
        "counterparty": item.counterparty if item else None,
        "description": item.description if item else None,
        "amount_cents": (item.amount_cents - item.paid_cents) if item else None,
        "from_date": change.from_date.isoformat(),
        "to_date": change.to_date.isoformat(),
        "status": change.status,
        "requested_by": change.requested_by,
        "requested_at": change.requested_at.isoformat(),
        "request_note": change.request_note,
        "decided_by": change.decided_by,
        "decided_at": change.decided_at.isoformat() if change.decided_at else None,
        "decision_note": change.decision_note,
    }


async def _load_change(db: AsyncSession, change_id: str) -> PaymentPlanChange:
    change = (
        await db.execute(select(PaymentPlanChange).where(PaymentPlanChange.id == change_id))
    ).scalar_one_or_none()
    if change is None:
        raise HTTPException(404, "Kayıt bulunamadı.")
    return change


async def _item(db: AsyncSession, change: PaymentPlanChange) -> OpenItem | None:
    return (await db.execute(select(OpenItem).where(OpenItem.id == change.open_item_id))).scalar_one_or_none()


@router.post("/ledger/plan-changes", status_code=201, response_model=Envelope[PlanChangeView])
async def propose_change(
    body: ProposeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    org_id = _org(current_user)
    try:
        change = await payment_plan.propose(
            db,
            user=current_user,
            org_id=org_id,
            open_item_id=body.open_item_id,
            to_date=body.to_date,
            note=body.note,
        )
    except PlanChangeError as exc:
        raise _fail(exc) from exc
    await db.commit()
    return {"data": _view(change, await _item(db, change)), "error": None}


@router.get("/ledger/plan-changes", response_model=PlanChangeList)
async def list_changes(
    status: str = Query(default="pending"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    org_id = _org(current_user)
    if status != "all" and status not in STATUSES:
        raise HTTPException(422, "Geçersiz durum.")
    query = select(PaymentPlanChange).where(PaymentPlanChange.org_id == org_id)
    if status != "all":
        query = query.where(PaymentPlanChange.status == status)
    rows = (await db.execute(query.order_by(PaymentPlanChange.requested_at.desc()))).scalars().all()
    items = {
        i.id: i
        for i in (
            await db.execute(select(OpenItem).where(OpenItem.id.in_([r.open_item_id for r in rows] or [""])))
        )
        .scalars()
        .all()
    }
    return {
        "data": [_view(r, items.get(r.open_item_id)) for r in rows],
        "meta": {"can_decide": payment_plan.can_decide(await acting_role(db, current_user))},
        "error": None,
    }


async def _apply_decision(
    db: AsyncSession, change: PaymentPlanChange, approve: bool, body: DecisionRequest, user: User
) -> dict[str, Any]:
    try:
        payment_plan.decide(
            change, user=user, role=await acting_role(db, user), approve=approve, note=body.note
        )
    except PlanChangeError as exc:
        raise _fail(exc) from exc
    await db.commit()
    return {"data": _view(change, await _item(db, change)), "error": None}


@router.post("/ledger/plan-changes/{change_id}/approve", response_model=Envelope[PlanChangeView])
async def approve_change(
    change_id: str,
    body: DecisionRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    change = await _load_change(db, change_id)
    ensure_tenant(current_user, org_id=change.org_id)
    return await _apply_decision(db, change, True, body or DecisionRequest(), current_user)


@router.post("/ledger/plan-changes/{change_id}/reject", response_model=Envelope[PlanChangeView])
async def reject_change(
    change_id: str,
    body: DecisionRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    change = await _load_change(db, change_id)
    ensure_tenant(current_user, org_id=change.org_id)
    return await _apply_decision(db, change, False, body or DecisionRequest(), current_user)


@router.post("/ledger/plan-changes/{change_id}/withdraw", response_model=Envelope[PlanChangeView])
async def withdraw_change(
    change_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    change = await _load_change(db, change_id)
    ensure_tenant(current_user, org_id=change.org_id)
    try:
        payment_plan.withdraw(change, user=current_user)
    except PlanChangeError as exc:
        raise _fail(exc) from exc
    await db.commit()
    return {"data": _view(change, await _item(db, change)), "error": None}
