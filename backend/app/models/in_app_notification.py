"""
InAppNotification — persisted in-app notification rows.

Frontend polls GET /api/v1/notifications to display the bell badge
and notification center list. Each row represents one actionable alert
that was routed to the "dashboard" channel.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class InAppNotification(Base):
    __tablename__ = "in_app_notifications"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    org_id: Mapped[str] = mapped_column(
        String(36), nullable=False, index=True
    )

    # Alert content
    level: Mapped[str] = mapped_column(
        String(20), nullable=False  # critical | warning | info
    )
    domain: Mapped[str] = mapped_column(
        String(50), nullable=False  # cfo | cto | cmo | risk | audit | ...
    )
    message: Mapped[str] = mapped_column(
        Text, nullable=False
    )
    source: Mapped[str] = mapped_column(
        String(100), nullable=False, default="pipeline"
    )
    job_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )

    # Routing metadata
    action: Mapped[str] = mapped_column(
        String(20), nullable=False, default="route"  # route | escalate
    )
    priority_score: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.5
    )

    # Read tracking
    is_read: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )
