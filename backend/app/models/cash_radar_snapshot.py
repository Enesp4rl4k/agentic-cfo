"""The radar's forecast as it was made, on the day it was made (Plan v10 O5).

A row is written once and never changed: grading a forecast against the bank balance
four weeks later is only honest if the forecast is the one the owner saw. A new forecast
is a new row. Rows are not protected against deletion, so a KVKK erasure of an
organisation can still remove them.
"""

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
    raise ValueError("Cash radar snapshots are immutable; write a new snapshot instead.")
