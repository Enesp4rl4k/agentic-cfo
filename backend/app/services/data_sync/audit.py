"""
Audit trail logging for all data sync operations.

Immutable log of every sync with:
  - Source, timestamp, status
  - Transaction counts
  - Data hash (SHA256) for integrity verification
  - Warnings/errors
  - Conflict resolutions
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, String, DateTime, Integer, Text, JSON, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.services.data_sync.schemas import (
    SyncBatch,
    SyncSourceType,
    SyncStatus,
    SyncJobLog,
)

logger = logging.getLogger(__name__)


class SyncAuditLog(Base):
    """Immutable log of each data sync operation."""

    __tablename__ = "sync_audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)

    # Source info
    source_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)

    # Timeline
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    ended_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Metrics
    transactions_synced: Mapped[int] = mapped_column(Integer, default=0)
    transactions_failed: Mapped[int] = mapped_column(Integer, default=0)
    conflict_count: Mapped[int] = mapped_column(Integer, default=0)

    # Data integrity
    data_hash: Mapped[str] = mapped_column(
        String(64), nullable=False
    )  # SHA256

    # Diagnostics
    warnings: Mapped[list[str]] = mapped_column(JSON, default=[])
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Indexes for common queries
    __table_args__ = (
        Index("idx_sync_source_date", "source_type", "started_at"),
        Index("idx_sync_status", "status", "started_at"),
    )


class AuditTrail:
    """Records all sync operations for audit and debugging."""

    def __init__(self):
        """Initialize audit trail."""
        pass

    @staticmethod
    def compute_batch_hash(batch: SyncBatch) -> str:
        """
        Compute SHA256 hash of batch for integrity verification.

        Hash includes all transaction data in deterministic order.
        """
        sorted_txs = sorted(
            batch.transactions,
            key=lambda t: (t.date.isoformat(), t.source_id or "", t.amount_cents),
        )

        batch_str = "\n".join(
            f"{t.date.isoformat()}|{t.source_id}|{t.amount_cents}|{t.vendor or ''}"
            for t in sorted_txs
        )

        return hashlib.sha256(batch_str.encode()).hexdigest()

    @staticmethod
    def create_sync_log(
        batch: SyncBatch,
        status: SyncStatus,
        started_at: datetime,
        ended_at: Optional[datetime] = None,
        error_message: Optional[str] = None,
        conflict_count: int = 0,
    ) -> SyncJobLog:
        """Create job log entry from batch."""
        duration_ms = None
        if ended_at:
            duration_ms = int((ended_at - started_at).total_seconds() * 1000)

        data_hash = AuditTrail.compute_batch_hash(batch)

        return SyncJobLog(
            source_type=batch.source_type,
            status=status,
            started_at=started_at,
            ended_at=ended_at,
            duration_ms=duration_ms,
            transactions_synced=len(batch.transactions),
            transactions_failed=batch.error_count,
            conflict_count=conflict_count,
            warnings=batch.warnings,
            error_message=error_message,
            data_hash=data_hash,
        )
