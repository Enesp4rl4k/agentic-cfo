"""A person's correction of one ledger row's category, kept so a re-read does not undo it.

A rerun recomputes an analysis from its file and writes new `Transaction` rows, which
carry only the standing (`apply_always`) rules. A correction of a single row is
remembered here by the row's ledger identity (`source_record_id`), and applied to the
rerun's rows before the ledger reads them (`services/ledger_correction.apply_overrides`).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class CategoryOverride(Base):
    __tablename__ = "category_overrides"
    __table_args__ = (
        UniqueConstraint("org_id", "source_record_id", name="uq_category_override_org_record"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    source_record_id: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
