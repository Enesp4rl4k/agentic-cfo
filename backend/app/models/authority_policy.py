"""AuthorityPolicy ORM — an org's editable Delegation-of-Authority matrix.

Versioned: `PUT /authority/policy` writes a new row (version + 1) and flips
`active`; older versions stay for the audit trail. Absent → the engine's default.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class AuthorityPolicy(Base):
    __tablename__ = "authority_policies"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    org_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)

    rules: Mapped[list] = mapped_column(JSON, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
