"""Changes to a payment plan, and the rule about who may decide them.

The owner's rule (docs/payment-plan-approval.md): a payment plan changes only with a senior
executive's approval. Any member may *propose*; only an owner or an admin may *decide*. An owner or
admin who proposes holds the authority themselves, so they may decide their own proposal (a company
with one owner would otherwise never be able to move a payment). Everyone else's proposal waits for
someone with the role. Nothing is overwritten: an approved change tells the radar when the payment
is expected and the document's own due date stays on the open item.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.open_item import OpenItem
from app.models.payment_plan_change import (
    APPROVED,
    PENDING,
    REJECTED,
    WITHDRAWN,
    PaymentPlanChange,
)
from app.models.user import User
from app.services.acting_role import acting_role

DECIDER_ROLES = frozenset({"owner", "admin"})
PROPOSER_ROLES = frozenset({"owner", "admin", "cfo", "analyst"})
MAX_DAYS_AHEAD = 366


class PlanChangeError(Exception):
    """A refusal the API turns into a status code and a plain sentence."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def can_decide(role: str) -> bool:
    return role in DECIDER_ROLES


async def effective_dates(db: AsyncSession, org_id: str) -> dict[str, date]:
    """Open item id → the date an *approved* change moved its payment to (latest decision wins)."""
    rows = (
        (
            await db.execute(
                select(PaymentPlanChange)
                .where(PaymentPlanChange.org_id == org_id, PaymentPlanChange.status == APPROVED)
                .order_by(PaymentPlanChange.decided_at)
            )
        )
        .scalars()
        .all()
    )
    return {r.open_item_id: r.to_date for r in rows}


async def propose(
    db: AsyncSession,
    *,
    user: User,
    org_id: str,
    open_item_id: str,
    to_date: date,
    note: str | None,
    today: date | None = None,
) -> PaymentPlanChange:
    if await acting_role(db, user) not in PROPOSER_ROLES:
        raise PlanChangeError(403, "Ödeme tarihi önermek için yazma yetkisi gerekir.")
    today = today or datetime.now(UTC).date()
    item = (
        await db.execute(select(OpenItem).where(OpenItem.id == open_item_id, OpenItem.org_id == org_id))
    ).scalar_one_or_none()
    if item is None:
        raise PlanChangeError(404, "Kayıt bulunamadı.")
    if item.direction != "payable":
        raise PlanChangeError(422, "Yalnızca ödemelerin tarihi taşınabilir; tahsilat tarihi bizim elimizde değil.")
    if item.status != "open" or item.amount_cents - item.paid_cents <= 0:
        raise PlanChangeError(422, "Bu ödeme kapanmış; tarihi taşınamaz.")
    if item.due_date is None:
        raise PlanChangeError(422, "Vadesi olmayan bir ödemenin tarihi taşınamaz.")
    if to_date < today or to_date > today + timedelta(days=MAX_DAYS_AHEAD):
        raise PlanChangeError(422, "Yeni tarih bugünden en fazla bir yıl sonrasına kadar olabilir.")

    effective = (await effective_dates(db, org_id)).get(item.id, item.due_date)
    if to_date == effective:
        raise PlanChangeError(422, "Yeni tarih ödemenin mevcut tarihiyle aynı.")
    pending = (
        await db.execute(
            select(PaymentPlanChange).where(
                PaymentPlanChange.open_item_id == item.id, PaymentPlanChange.status == PENDING
            )
        )
    ).scalar_one_or_none()
    if pending is not None:
        raise PlanChangeError(409, "Bu ödeme için karar bekleyen bir öneri zaten var.")

    change = PaymentPlanChange(
        org_id=org_id,
        open_item_id=item.id,
        from_date=effective,
        to_date=to_date,
        requested_by=str(user.id),
        request_note=(note or "").strip() or None,
    )
    db.add(change)
    await db.flush()
    return change


def _ensure_pending(change: PaymentPlanChange) -> None:
    if change.status != PENDING:
        raise PlanChangeError(409, "Bu öneri için karar zaten verilmiş.")


def decide(
    change: PaymentPlanChange, *, user: User, role: str, approve: bool, note: str | None
) -> PaymentPlanChange:
    """Approve or reject. Only an owner or an admin; a rejection keeps its reason."""
    if role not in DECIDER_ROLES:
        raise PlanChangeError(403, "Ödeme planı değişikliğini yalnızca sahip ya da yönetici onaylayabilir.")
    _ensure_pending(change)
    change.status = APPROVED if approve else REJECTED
    change.decided_by = str(user.id)
    change.decided_at = datetime.now(UTC)
    change.decision_note = (note or "").strip() or None
    return change


def withdraw(change: PaymentPlanChange, *, user: User) -> PaymentPlanChange:
    """Only the person who proposed it, and only while it waits."""
    if str(user.id) != change.requested_by:
        raise PlanChangeError(403, "Öneriyi yalnızca öneren kişi geri çekebilir.")
    _ensure_pending(change)
    change.status = WITHDRAWN
    change.decided_by = str(user.id)
    change.decided_at = datetime.now(UTC)
    return change
