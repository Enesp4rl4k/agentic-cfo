"""Alert rules and their firing history.

Like `compliance_extended`, these two tables lived only in a migration (018) and
were reached with raw SQL. Nothing declared them, so `create_all` never made them
on SQLite — and unlike the compliance routes, `ws_alerts` swallows its query
errors, so the endpoints answered 200 with an empty list instead of failing.
That is the worse half of the same bug: no error to notice.

Columns mirror migration 018 exactly; no schema change.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AlertRule(Base):
    """One threshold rule: fire when `metric` `operator` `threshold`."""

    __tablename__ = "alert_rules"
    __table_args__ = (Index("ix_alert_rules_org_enabled", "org_id", "enabled"),)

    id: Mapped[str] = mapped_column(
        String(32), primary_key=True, default=lambda: uuid.uuid4().hex
    )
    org_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # e.g. cash_runway_months, anomaly_count_critical
    metric: Mapped[str] = mapped_column(String(100), nullable=False)
    operator: Mapped[str] = mapped_column(String(10), nullable=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    # JSON list, stored as text to match migration 018: ["slack", "email", …]
    channels: Mapped[str | None] = mapped_column(Text, nullable=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="warning")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def to_dict(self) -> dict[str, Any]:
        import json

        try:
            channels = json.loads(self.channels) if self.channels else []
        except (TypeError, ValueError):
            channels = []
        return {
            "id": self.id,
            "name": self.name,
            "metric": self.metric,
            "operator": self.operator,
            "threshold": self.threshold,
            "channels": channels,
            "severity": self.severity,
            "enabled": bool(self.enabled),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class AlertHistory(Base):
    """One alert that fired, and whether a human acknowledged it."""

    __tablename__ = "alert_history"
    __table_args__ = (Index("ix_alert_history_org_created", "org_id", "created_at"),)

    id: Mapped[str] = mapped_column(
        String(32), primary_key=True, default=lambda: uuid.uuid4().hex
    )
    org_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    # Nullable on purpose: not every alert comes from a rule.
    rule_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="warning")
    source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    channels_sent: Mapped[str | None] = mapped_column(Text, nullable=True)
    acknowledged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    acknowledged_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def to_dict(self) -> dict[str, Any]:
        import json

        try:
            channels = json.loads(self.channels_sent) if self.channels_sent else []
        except (TypeError, ValueError):
            channels = []
        return {
            "id": self.id,
            "rule_id": self.rule_id,
            "message": self.message,
            "severity": self.severity,
            "source": self.source,
            "channels_sent": channels,
            "acknowledged": bool(self.acknowledged),
            "acknowledged_by": self.acknowledged_by,
            "acknowledged_at": (
                self.acknowledged_at.isoformat() if self.acknowledged_at else None
            ),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
