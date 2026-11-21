"""Organisation erasure bookkeeping (KVKK Md. 7 / GDPR Art. 17).

Two tables, neither of which holds personal data once an erasure has run:

* `OrgErasureRequest` — the two-step handshake. An owner/admin *requests*, the
  owner *confirms*. While pending it names the target organisation; on execution
  `target_org_id` and `requested_by_user_id` are nulled and only hashes remain.
* `OrgErasureRecord` — the append-only, hash-chained proof that an erasure
  happened: who (hash), when, which org (hash), how many rows per table.
  `record_hash` covers the content plus the previous record's hash, so a row
  edited or removed afterwards breaks verification (`verify_chain`).

Neither table has an `org_id` column on purpose: erasing an organisation must not
erase the evidence of its erasure. They are listed in
`app.services.org_erasure.BOOKKEEPING_TABLES`.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class OrgErasureRequest(Base):
    __tablename__ = "org_erasure_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    # Nulled when the erasure executes. Not named `org_id` — see module docstring.
    target_org_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    org_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    mode: Mapped[str] = mapped_column(String(20), nullable=False)  # anonymise | hard_delete
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    requested_by_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    requested_by_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confirmed_by_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    record_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class OrgErasureRecord(Base):
    __tablename__ = "org_erasure_records"
    __table_args__ = (UniqueConstraint("seq", name="uq_org_erasure_records_seq"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    org_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    mode: Mapped[str] = mapped_column(String(20), nullable=False)
    requested_by_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confirmed_by_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    counts: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    record_hash: Mapped[str] = mapped_column(String(64), nullable=False)
