from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class CanonicalTransaction(Base):
    """
    Source-agnostic transaction contract used by the data plane.

    All connectors should normalize into this structure so downstream
    agents do not need provider-specific mapping logic.
    """

    __tablename__ = "canonical_transactions"
    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "source_type",
            "source_record_id",
            name="uq_canonical_tx_org_source_record",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    org_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    source_record_id: Mapped[str] = mapped_column(String(120), nullable=False)
    sync_run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("sync_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )

    transaction_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # See Transaction.date_is_estimated — same reason, same rule.
    date_is_estimated: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="0"
    )
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="TRY")
    direction: Mapped[str] = mapped_column(String(20), nullable=False, default="expense")
    category: Mapped[str | None] = mapped_column(String(80), nullable=True)
    counterparty: Mapped[str | None] = mapped_column(String(200), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

