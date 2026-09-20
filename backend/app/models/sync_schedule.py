"""SyncSchedule ORM — scheduled data pulls (DQ-5)."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class SyncSchedule(Base):
    __tablename__ = "sync_schedules"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    org_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    frequency: Mapped[str] = mapped_column(String(20), nullable=False, default="daily")
    hour_utc: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    auto_analyze: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notify_on_completion: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    source_config: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(20), nullable=True, default="idle")
    last_job_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    last_row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_health_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
