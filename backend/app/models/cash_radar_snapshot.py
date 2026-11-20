"""Immutable, content-addressed cash radar projections for forecast evaluation."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import JSON, Date, DateTime, Index, String, UniqueConstraint, event
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CashRadarSnapshot(Base):
    __tablename__ = "cash_radar_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "org_id", "anchor_date", "snapshot_hash", name="uq_cash_radar_snapshot_content"
        ),
        Index("ix_cash_radar_snapshots_org_anchor", "org_id", "anchor_date"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(36), nullable=False)
    anchor_date: Mapped[date] = mapped_column(Date, nullable=False)
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


@event.listens_for(CashRadarSnapshot, "before_update")
def _reject_update(*_: object) -> None:
    raise ValueError("Cash radar snapshots are immutable; insert a new snapshot instead.")


@event.listens_for(CashRadarSnapshot, "before_delete")
def _reject_delete(*_: object) -> None:
    raise ValueError("Cash radar snapshots are immutable and cannot be deleted.")
