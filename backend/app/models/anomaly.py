"""
Anomaly — detected financial anomalies for a job.

Each row represents one anomalous pattern found in the transaction set.
Severity: low | medium | high | critical
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import String, DateTime, Text, JSON, Numeric, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import TYPE_CHECKING

from app.database import Base

if TYPE_CHECKING:
    from app.models.analysis_job import AnalysisJob


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AnomalySeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AnomalyType(StrEnum):
    DUPLICATE_PAYMENT   = "duplicate_payment"
    UNUSUAL_AMOUNT      = "unusual_amount"
    UNUSUAL_VENDOR      = "unusual_vendor"
    VENDOR_CONCENTRATION = "vendor_concentration"
    NEGATIVE_CASHFLOW_STREAK = "negative_cashflow_streak"
    EXPENSE_SPIKE       = "expense_spike"
    MISSING_REVENUE     = "missing_revenue"
    ROUND_NUMBER        = "round_number"   # fraud indicator
    LATE_PAYMENT        = "late_payment"
    FX_CONCENTRATION    = "fx_concentration"


class Anomaly(Base):
    __tablename__ = "anomalies"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_jobs.id"), nullable=False, index=True
    )

    anomaly_type: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)

    # Human-readable title and explanation
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # The transactions involved (list of transaction IDs)
    transaction_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # Supporting data (amounts, z-score, etc.)
    evidence: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Statistical confidence 0–1
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)

    # Whether the user has acknowledged/dismissed this anomaly
    acknowledged: Mapped[bool] = mapped_column(default=False, nullable=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    job: Mapped["AnalysisJob"] = relationship("AnalysisJob")
