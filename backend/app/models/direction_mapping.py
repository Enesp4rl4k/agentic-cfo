"""A statement format's direction, answered once for an organisation.

When a file's direction cannot be placed (`app.parsers.direction`) a person answers one
question for the whole file. For the same organisation and the same header signature the
answer is remembered here, so the next upload of that bank's format is not asked again.
It is listed on `/bekleyen-kayitlar` and can be revoked there; a revoked mapping is kept
(`revoked_at`), never deleted, so the decision that created it still has its record.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class DirectionMapping(Base):
    __tablename__ = "direction_mappings"
    __table_args__ = (Index("ix_direction_mappings_org_sig", "org_id", "signature"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(36), nullable=False)
    # `app.parsers.direction.header_signature`: the file's header words, in order.
    signature: Mapped[str] = mapped_column(String(32), nullable=False)
    # Why the file waited (`no_signal` | `balance_contradicts`): an answer is only reused for the same question.
    reason: Mapped[str] = mapped_column(String(24), nullable=False)
    # as_read | balance | all_income | all_expense (`app.services.held_direction.ANSWERS`)
    answer: Mapped[str] = mapped_column(String(16), nullable=False)
    # What the person saw when they answered: the header names, for the list on the screen.
    columns: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
