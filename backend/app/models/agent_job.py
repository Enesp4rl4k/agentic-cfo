"""
AgentJob — Async job queue for non-CFO agents.

Desteklenen agent tipleri: cto, cmo, coo, chro, risk, audit, compliance
Her job: input CSV/text → pipeline çalışır → result_json'a yazılır.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class AgentJobStatus(StrEnum):
    PENDING   = "pending"
    RUNNING   = "running"
    COMPLETED = "completed"
    FAILED    = "failed"


# Supported agent types
AGENT_TYPES = frozenset({"cto", "cmo", "coo", "chro", "risk", "audit", "compliance"})


class AgentJob(Base):
    __tablename__ = "agent_jobs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    # Which agent runs this job
    agent_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)

    # Multi-tenant scoping
    user_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    org_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Job lifecycle
    status: Mapped[str] = mapped_column(
        String(20), default=AgentJobStatus.PENDING, nullable=False, index=True
    )

    # Input: one or more named CSV/text fields (e.g. {"infra_csv": "...", "debt_csv": "..."})
    input_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Output: the full agent result dict
    result_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Step-level logs (list of {step, ok, detail, ts})
    logs: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # Error message on failure
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Progress 0–100 for frontend polling
    progress: Mapped[int] = mapped_column(default=0, nullable=False)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
