"""Scheduler bookkeeping that must survive a restart: which due runs happened, and operator-facing state.

`ScheduledJobRun`: one row per (job, organisation, period). The unique key is what makes a scheduled job
safe to catch up and to run in two processes: whoever inserts the row owns the run; a finished row is never
run again. `status`: running | done | failed. A `running` row whose claim is older than the lease belongs
to a process that died and may be taken over.

`OpsState`: small named documents the operators need (the last backup report). Not business data.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

RUNNING = "running"
DONE = "done"
FAILED = "failed"

GLOBAL_SCOPE = "*"  # `org_id` of a job that is not per company


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ScheduledJobRun(Base):
    __tablename__ = "scheduled_job_runs"
    __table_args__ = (UniqueConstraint("job", "org_id", "period", name="uq_scheduled_job_runs_job_org_period"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    org_id: Mapped[str] = mapped_column(String(36), nullable=False)
    period: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default=RUNNING)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    claimed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(300), nullable=True)


class OpsState(Base):
    __tablename__ = "ops_state"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
