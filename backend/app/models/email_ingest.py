"""An organisation's mail address for data, and the mail that arrived at it.

A person sets up forwarding once — their bank's statement mail, their
accountant's monthly export — and the files arrive without anyone opening the
app. The address carries a random code: knowing it is what lets mail in, so it
can be replaced, and every message that came through it is kept on record
where the organisation can see it.
"""
from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


def yeni_kod() -> str:
    """80 bits, lower-case letters and digits: safe in an address, not guessable."""
    alfabe = "abcdefghijklmnopqrstuvwxyz0123456789"
    return "".join(secrets.choice(alfabe) for _ in range(16))


class EmailIngestAddress(Base):
    __tablename__ = "email_ingest_addresses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    kod: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True, default=yeni_kod)
    # Jobs started from mail are filed under the person who set the address up.
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EmailIngestMessage(Base):
    __tablename__ = "email_ingest_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    address_id: Mapped[str] = mapped_column(String(36), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    sender: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    subject: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    message_id: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Per attachment: name, sha256, what it was recognised as and what happened.
    sonuclar: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
