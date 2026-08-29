"""ORM model for company semantic snapshots."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _jsonb_or_text():
    try:
        from app.config import get_settings

        s = get_settings()
        if not s.use_sqlite:
            from sqlalchemy.dialects.postgresql import JSONB

            return JSONB(astext_type=Text())
    except Exception:
        pass
    return Text()


class CompanySemanticSnapshotRow(Base):
    """
    Versioned org+period semantic snapshot.

    metrics_json / drivers_json / evidence_json / brief_json store
    serialized lists/dicts from services.semantic.types.
    """

    __tablename__ = "company_semantic_snapshots"
    __table_args__ = (
        UniqueConstraint("org_id", "period_key", name="uq_semantic_org_period"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    org_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    period_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    period_start: Mapped[str | None] = mapped_column(String(32), nullable=True)
    period_end: Mapped[str | None] = mapped_column(String(32), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")
    locale: Mapped[str] = mapped_column(String(16), nullable=False, default="en-US")
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False, default="1.0.0")

    metrics_json: Mapped[str] = mapped_column(_jsonb_or_text(), nullable=False, default="[]")
    drivers_json: Mapped[str] = mapped_column(_jsonb_or_text(), nullable=False, default="[]")
    evidence_json: Mapped[str] = mapped_column(_jsonb_or_text(), nullable=False, default="[]")
    brief_json: Mapped[str | None] = mapped_column(_jsonb_or_text(), nullable=True)
    source_job_ids: Mapped[str] = mapped_column(_jsonb_or_text(), nullable=False, default="[]")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
