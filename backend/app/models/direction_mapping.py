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

from sqlalchemy import Boolean, DateTime, Index, String
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
    # The sign memory (`sign_unconfirmed`) is applied silently only to the SAME SOURCE: `signature` includes the account
    # identity the file's header states, `header_signature` is the header words alone (to name an earlier source when a
    # file with the same headers but no / another identity is asked again), `identity` is what the header stated ("" none).
    header_signature: Mapped[str | None] = mapped_column(String(32), nullable=True)
    identity: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # An explicit, recorded choice "files with these headers and no account named are always so": the only way an
    # identity-less file is applied silently. Never inferred.
    standing: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    # A balance chain contradicted this memory and won: when, and what was recorded (never silent).
    flagged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    flagged_note: Mapped[str | None] = mapped_column(String(300), nullable=True)
