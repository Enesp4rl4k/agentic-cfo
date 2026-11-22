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

from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.access import ensure_tenant
from app.api.auth import get_current_user
from app.api.contract import Envelope
from app.database import get_db
from app.models.decision import DecidedVia, Decision, DecisionKind
from app.models.open_item import OpenItem
from app.models.organization import Organization
from app.models.payment_plan_change import PENDING, STATUSES, PaymentPlanChange
from app.models.user import User
from app.services import materiality, payment_plan, self_approval
from app.services.acting_role import acting_role
from app.services.decisions import record_decision
from app.services.payment_plan import PlanChangeError

router = APIRouter()


class ProposeRequest(BaseModel):
    open_item_id: str
    to_date: date
    note: str | None = Field(default=None, max_length=1000)


class DecisionRequest(BaseModel):
    note: str | None = Field(default=None, max_length=1000)
    # Needed only to approve one's own proposal: the sentence `self_approval.SELF_DECISION_ACK`.
    self_decision_ack: str | None = Field(default=None, max_length=500)


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
    # What the caller may do with their OWN waiting proposal: "acknowledge" (decide it after confirming that
    # proposer and approver are the same person), "blocked" (another decider must), else null.
    self_decision: str | None = None
    self_decision_message: str | None = None
    # The proposer changed the company's approval threshold shortly before or after proposing: said to
    # whoever decides, so the audit does not depend on someone noticing the settings history.
    threshold_changed_by_proposer: bool = False


class PlanChangeListMeta(BaseModel):
    can_decide: bool
    self_decision_ack: str = self_approval.SELF_DECISION_ACK


class PlanChangeList(Envelope[list[PlanChangeView]]):
    meta: PlanChangeListMeta  # type: ignore[assignment]  # narrows the envelope's free-form meta


def _org(user: User) -> str:
    if not user.org_id:
        raise HTTPException(400, "Bu işlem için bir organizasyon gerekli.")
    return str(user.org_id)


def _fail(exc: PlanChangeError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=exc.message)


def _view(
    change: PaymentPlanChange, item: OpenItem | None, self_state: self_approval.SelfDecision | None = None,
    threshold_moved: bool = False,
) -> dict[str, Any]:
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
        "self_decision": self_state.state if self_state and self_state.state != self_approval.NOT_SELF else None,
        "self_decision_message": self_state.message if self_state else None,
        "threshold_changed_by_proposer": threshold_moved,
    }


async def _threshold_movers(db: AsyncSession, org_id: str) -> list[tuple[str, datetime]]:
    """Who changed the company's materiality threshold, and when (recent changes only)."""
    since = datetime.now(UTC) - timedelta(days=2 * self_approval.SELF_APPROVAL_WINDOW_DAYS)
    rows = (
        await db.execute(
            select(Decision.decided_by, Decision.decided_at).where(
                Decision.org_id == org_id, Decision.kind == DecisionKind.MATERIALITY.value,
                Decision.decided_at >= since,
            )
        )
    ).all()
    return [(str(who), at) for who, at in rows if who]


def _moved(change: PaymentPlanChange, movers: list[tuple[str, datetime]]) -> bool:
    """Did the proposer change the threshold within the window before the proposal, or after it?"""
    window = timedelta(days=self_approval.SELF_APPROVAL_WINDOW_DAYS)
    asked = change.requested_at if change.requested_at.tzinfo else change.requested_at.replace(tzinfo=UTC)
    return any(
        who == change.requested_by and (at if at.tzinfo else at.replace(tzinfo=UTC)) >= asked - window
        for who, at in movers
    )


async def _self_state(
    db: AsyncSession, change: PaymentPlanChange, item: OpenItem | None, user: User, role: str
) -> self_approval.SelfDecision:
    """The caller's position on their own waiting proposal (`services/self_approval`)."""
    if change.status != PENDING or change.requested_by != str(user.id) or not payment_plan.can_decide(role):
        return self_approval.SelfDecision(self_approval.NOT_SELF)
    # Judged against the threshold in force when it was proposed (a later change does not reach it); a row
    # older than that column falls back to the current one. An item that is gone is an unknown amount.
    org = await db.get(Organization, str(change.org_id))
    threshold = change.threshold_cents if change.threshold_cents is not None else materiality.threshold_cents(org)
    threshold_cur = change.threshold_currency or materiality.threshold_currency(org)
    currency = item.currency if item else None
    return self_approval.assess(
        proposer_id=change.requested_by, user_id=str(user.id),
        others=await self_approval.other_decider_exists(db, str(change.org_id), str(user.id)),
        amount_cents=(item.amount_cents - item.paid_cents) if item else None, currency=currency,
        threshold=threshold, threshold_currency=threshold_cur,
        prior_cents=await self_approval.self_approved_total(db, str(change.org_id), str(user.id), currency),
    )


async def _record(
    db: AsyncSession, change: PaymentPlanChange, user: User, outcome: str, *, reason: str | None = None,
    acknowledgement: str | None = None, item: OpenItem | None = None,
) -> None:
    """One decision record per step of a proposal's life, in the caller's transaction.

    `proposed` is the member's request; `approved`, `rejected` and `withdrawn` close it. An owner or an
    admin who decides their own proposal (the rule: they hold the authority) leaves a `proposed` and an
    `approved`, both theirs, and the approval says `self_decided` so nobody reads it as a second pair of eyes.
    """
    after: dict[str, Any] = {"from_date": change.from_date.isoformat(), "to_date": change.to_date.isoformat(), "status": change.status}
    if outcome in ("approved", "rejected"):
        after["self_decided"] = change.requested_by == str(user.id)
        if after["self_decided"] and outcome == "approved" and item is not None:
            # What the person approved for themselves: the next self-approval is judged with it
            # (`self_approval.self_approved_total`).
            after["amount_cents"] = item.amount_cents - item.paid_cents
            after["currency"] = item.currency
            after["threshold_cents"] = change.threshold_cents
        if acknowledgement:
            after["self_decision_ack"] = acknowledgement
    await record_decision(
        db, org_id=str(change.org_id), kind=DecisionKind.PLAN_CHANGE, target_type="payment_plan_change",
        target_id=str(change.id), outcome=outcome, decided_via=DecidedVia.HUMAN, decided_by=str(user.id),
        reason=reason, evidence_refs=[{"type": "open_item", "id": str(change.open_item_id)}],
        before=None if outcome == "proposed" else {"status": PENDING},
        after=after,
    )


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
    await _record(db, change, current_user, "proposed", reason=change.request_note)
    await db.commit()
    item = await _item(db, change)
    state = await _self_state(db, change, item, current_user, await acting_role(db, current_user))
    moved = _moved(change, await _threshold_movers(db, org_id))
    return {"data": _view(change, item, state, moved), "error": None}


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
    role = await acting_role(db, current_user)
    states = {r.id: await _self_state(db, r, items.get(r.open_item_id), current_user, role) for r in rows}
    movers = await _threshold_movers(db, org_id)
    return {
        "data": [_view(r, items.get(r.open_item_id), states[r.id], _moved(r, movers)) for r in rows],
        "meta": {"can_decide": payment_plan.can_decide(role), "self_decision_ack": self_approval.SELF_DECISION_ACK},
        "error": None,
    }


async def _apply_decision(
    db: AsyncSession, change: PaymentPlanChange, approve: bool, body: DecisionRequest, user: User
) -> dict[str, Any]:
    role = await acting_role(db, user)
    acknowledgement: str | None = None
    if payment_plan.can_decide(role) and change.status == PENDING:
        # Deciding one's own proposal: one honest step, or not at all (`services/self_approval`).
        state = await _self_state(db, change, await _item(db, change), user, role)
        if state.state == self_approval.BLOCKED and approve:
            raise HTTPException(403, state.message)
        if state.state == self_approval.ACKNOWLEDGE and approve:
            if body.self_decision_ack != self_approval.SELF_DECISION_ACK:
                raise HTTPException(422, "Öneren ve onaylayan aynı kişi: devam etmek için bunu onaylamanız gerekir.")
            acknowledgement = body.self_decision_ack
    try:
        payment_plan.decide(change, user=user, role=role, approve=approve, note=body.note)
    except PlanChangeError as exc:
        raise _fail(exc) from exc
    item = await _item(db, change)
    await _record(
        db, change, user, "approved" if approve else "rejected", reason=change.decision_note,
        acknowledgement=acknowledgement, item=item,
    )
    await db.commit()
    return {"data": _view(change, item), "error": None}


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
    await _record(db, change, current_user, "withdrawn")
    await db.commit()
    return {"data": _view(change, await _item(db, change)), "error": None}
