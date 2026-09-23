"""DecisionLog — the organisation's decision ledger. (P2 · Karar Defteri)

A decision is recorded ONCE, at the moment it is made, with the packet's
own numbers snapshotted server-side (`expected`): nobody can rewrite what
they expected afterwards. Measuring later writes `actual` + `variance`
and closes the row — the loop decision → expectation → outcome that the
boardroom file never closed.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.analysis_job import AnalysisJob


def utcnow() -> datetime:
    return datetime.now(UTC)


class DecisionLog(Base):
    __tablename__ = "decision_logs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    # Nullable like AnalysisJob.org_id: an org-less job's decision still
    # belongs to the user who made it (access falls back to created_by).
    org_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_jobs.id"), nullable=False, index=True
    )

    topic: Mapped[str] = mapped_column(String(300), nullable=False)
    chosen_option_id: Mapped[str] = mapped_column(String(50), nullable=False)
    chosen_option_label: Mapped[str] = mapped_column(String(200), nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Server-filled from the packet at decision time — the human chooses
    # an option and writes a why; they never author the figures.
    expected: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # open → measured exactly once → closed.
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open", index=True)

    actual: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    variance: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    outcome_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    measured_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    job: Mapped[AnalysisJob] = relationship("AnalysisJob")
