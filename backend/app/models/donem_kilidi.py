"""A month an organisation's accountant has closed.

Once closed, the month's ledger rows do not change; a change that belongs to it is
booked in the first open month and marked with the closed period
(`CanonicalTransaction.asil_donem`). See `app/services/donem_kilidi.py`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class DonemKilidi(Base):
    __tablename__ = "donem_kilitleri"
    __table_args__ = (UniqueConstraint("org_id", "donem", name="uq_donem_kilidi_org_donem"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    donem: Mapped[str] = mapped_column(String(7), nullable=False)  # "YYYY-MM"
    kilitleyen_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
