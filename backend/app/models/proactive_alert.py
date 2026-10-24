"""proactive_alerts — the durable log of KRI / cascade alerts the hourly scan raises.

The table has existed since migration 009, but no model did: the orchestrator
wrote it with raw SQL (CLAUDE.md law 4), SQLite dev databases — built by
`create_all` from the models — never had the table, and every insert failed
into an `except: pass` (plan v6 §S0). The columns mirror migration 009 exactly;
`created_at` is a Unix timestamp (float), as the orchestrator has always
written it.
"""
from __future__ import annotations

from sqlalchemy import Boolean, Float, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ProactiveAlert(Base):
    __tablename__ = "proactive_alerts"
    __table_args__ = (
        Index("ix_proactive_alerts_org", "org_id"),
        Index("ix_proactive_alerts_severity", "severity"),
    )

    alert_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    org_id: Mapped[str] = mapped_column(String(36), nullable=False)
    trigger: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    # "metadata" is reserved on declarative classes; the column keeps its name.
    metadata_json: Mapped[str | None] = mapped_column("metadata", Text, nullable=True)
    channels: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    dispatched: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
