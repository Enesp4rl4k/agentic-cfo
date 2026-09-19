"""InstitutionalizationSnapshot ORM — the "Kurumsallaşma Endeksi" over time.

Differentiator #1 of the family-business-institutionalisation thesis. A snapshot
scores the org (0–100) across six dimensions from signals the platform already
produces — authority matrix usage, review throughput, decision traceability,
run cadence, key-person concentration — so a family can see, and track, how far
along institutionalisation they are. Stored on each computation for the trend.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class InstitutionalizationSnapshot(Base):
    __tablename__ = "institutionalization_snapshots"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    org_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    overall_score: Mapped[int] = mapped_column(Integer, nullable=False)
    grade: Mapped[str] = mapped_column(String(2), nullable=False)  # A | B | C | D | E

    dimensions: Mapped[list] = mapped_column(JSON, nullable=False)      # [{key,label,score,why,weight}]
    recommendations: Mapped[list] = mapped_column(JSON, nullable=False)  # [{dimension,text,impact}]
    signals: Mapped[dict] = mapped_column(JSON, nullable=False)          # raw counters for audit

    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
