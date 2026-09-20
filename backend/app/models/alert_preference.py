"""
AlertPreference — per-org notification channel configuration.

One row per org. Controls:
  - Which channels receive alerts (email, slack, dashboard)
  - Minimum severity threshold (info / warning / critical)
  - Slack webhook URL (per-org override)
  - Email recipients list (JSON array)
  - Quiet hours (no alerts during these hours)
  - Daily digest mode vs. real-time alerts
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class AlertPreference(Base):
    __tablename__ = "alert_preferences"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    org_id: Mapped[str] = mapped_column(
        String(36), unique=True, nullable=False, index=True
    )

    # Active channels — JSON array: ["email", "slack", "dashboard"]
    channels: Mapped[str] = mapped_column(
        Text, nullable=False, default='["dashboard"]'
    )

    # Minimum severity to trigger notification
    # "info" | "warning" | "critical"
    min_severity: Mapped[str] = mapped_column(
        String(20), nullable=False, default="warning"
    )

    # Slack integration
    slack_webhook_url: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )
    slack_channel: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )

    # Email integration — JSON array of email addresses
    email_recipients: Mapped[str | None] = mapped_column(
        Text, nullable=True  # JSON: ["cfo@company.com", "ceo@company.com"]
    )

    # WhatsApp integration (Meta Cloud API or Twilio)
    # Store the recipient phone number with country code (e.g. "+905551234567")
    whatsapp_number: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )

    # Digest mode: True = one daily summary, False = real-time per alert
    daily_digest_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    digest_hour_utc: Mapped[int] = mapped_column(
        Integer, nullable=False, default=7  # 07:00 UTC = 10:00 Istanbul
    )

    # Quiet hours — suppress non-critical alerts during these hours (UTC)
    quiet_hours_start: Mapped[int | None] = mapped_column(
        Integer, nullable=True  # e.g. 23
    )
    quiet_hours_end: Mapped[int | None] = mapped_column(
        Integer, nullable=True  # e.g. 7
    )

    # Only notify for escalated (executive-level) alerts?
    escalation_only: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
