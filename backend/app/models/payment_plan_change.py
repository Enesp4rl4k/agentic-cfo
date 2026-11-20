"""A proposed change to when a payable is paid, and who decided it.

The owner's rule (docs/payment-plan-approval.md): nobody changes a payment plan alone. A member
proposes; the owner or an admin decides. The row is the whole record: who asked, when, for which
date, who decided, when, and why. Nothing is overwritten: the document's own due date stays on the
open item, and an approved change only tells the radar when the payment is expected.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import Date, DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

PENDING = "pending"
APPROVED = "approved"
REJECTED = "rejected"
WITHDRAWN = "withdrawn"
STATUSES = (PENDING, APPROVED, REJECTED, WITHDRAWN)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class PaymentPlanChange(Base):
    __tablename__ = "payment_plan_changes"
    __table_args__ = (
        Index("ix_payment_plan_changes_org_status", "org_id", "status"),
        Index("ix_payment_plan_changes_item", "open_item_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(36), nullable=False)
    open_item_id: Mapped[str] = mapped_column(String(36), nullable=False)
    # The date the payment stood at when it was proposed, and the date asked for.
    from_date: Mapped[date] = mapped_column(Date, nullable=False)
    to_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default=PENDING)
    requested_by: Mapped[str] = mapped_column(String(36), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    request_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
