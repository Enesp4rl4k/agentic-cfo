"""An extracted row that waits for a person before it counts.

A row whose confidence is unknown or low, or whose currency is unknown, is not
written to `transactions` (so the ledger, the radar and every total leave it out)
but kept here, whole, with the reasons. A person releases it (it becomes a
`Transaction` and joins the ledger) or rejects it. Nothing is guessed in between.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

PENDING = "pending"
RELEASED = "released"
REJECTED = "rejected"


def _utcnow() -> datetime:
    return datetime.now(UTC)


class HeldTransaction(Base):
    __tablename__ = "held_transactions"
    __table_args__ = (
        Index("ix_held_transactions_org_status", "org_id", "status"),
        Index("ix_held_transactions_org_key", "org_id", "row_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_jobs.id"), nullable=False, index=True
    )
    org_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # Stable identity of the row's content (see `app.services.held_rows.row_key`): the
    # same row seen again — a re-upload, a rerun — is the same question, asked once.
    row_key: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    # The row as extracted (the pipeline's transaction dict), `hold_reasons` included.
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default=PENDING)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
