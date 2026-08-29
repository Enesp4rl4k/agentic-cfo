"""DefensibilityPacket ORM — the SMMM's audit-defence artifact per period.

Differentiator #4. In Turkey the SMMM (certified accountant) is personally liable
for the books. This is the single, hash-sealed record they can hand a tax
inspector: every journal entry with its basis, its AI classification + confidence,
whether a human reviewed it (approved / corrected / rejected) or the AI posted it
automatically, plus the run's independent-reconciliation verdict and confidence
decomposition. Once `finalized` the payload is frozen and `content_hash` locks it.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class DefensibilityPacket(Base):
    __tablename__ = "defensibility_packets"
    __table_args__ = (
        UniqueConstraint("org_id", "job_id", name="uq_defensibility_org_job"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    org_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    job_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    period: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="draft", index=True
    )  # draft | finalized

    # SHA-256 over the canonical serialization of `payload` — tamper evidence.
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    smmm_statement: Mapped[str | None] = mapped_column(Text, nullable=True)
    finalized_by_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    finalized_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
