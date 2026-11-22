"""An external effect waiting to happen, or the record that it happened (plan v11 C9).

Business code does not send mail; it writes a row here keyed by what the message is
for. The key is unique, so writing the same effect twice writes nothing new, and a
message that could not go out stays with its reason instead of vanishing.

Status: pending → sent | failed; held waits for a person (an accountant's release).

Class: `released` (the default) is business content: it goes out under an organisation's
standing preference (pending) or after a person's release (held → pending), and only to a
recipient the organisation has configured. `immediate` is transactional security mail that
needs no release and carries no business data; only the template kinds allowlisted in
`app.services.outbox_immediate` can be written as `immediate`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

PENDING = "pending"
HELD = "held"
SENT = "sent"
FAILED = "failed"

RELEASED = "released"
IMMEDIATE = "immediate"


class OutboxMessage(Base):
    __tablename__ = "outbox_messages"
    __table_args__ = (Index("ix_outbox_messages_status_created", "status", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    org_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    recipient: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    source_ref: Mapped[str] = mapped_column(String(100), nullable=False)
    delivery_class: Mapped[str] = mapped_column(
        String(20), nullable=False, default=RELEASED, server_default=RELEASED
    )
    kind: Mapped[str | None] = mapped_column(String(50), nullable=True)
    transport: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=PENDING)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
