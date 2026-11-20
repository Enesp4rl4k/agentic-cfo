"""A bank movement paying an open item, or perhaps paying it.

Kept as its own record so a settlement can be traced to the line that made it, a
"no" is remembered, and how late a customer really pays can be measured.
"""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import BigInteger, CheckConstraint, Date, DateTime, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class OpenItemMatch(Base):
    __tablename__ = "open_item_matches"
    __table_args__ = (
        Index("ix_open_item_matches_org_status", "org_id", "status"),
        Index("ix_open_item_matches_row", "ledger_row_id"),
        # One record per bank row and invoice: a second pass cannot add the
        # same payment again (migration 057).
        UniqueConstraint("ledger_row_id", "open_item_id", name="uq_open_item_matches_row_item"),
        # Migration 059.
        CheckConstraint("status IN ('confirmed', 'proposed', 'rejected')", name="ck_open_item_matches_status"),
        CheckConstraint("amount_cents > 0", name="ck_open_item_matches_amount"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(36), nullable=False)
    open_item_id: Mapped[str] = mapped_column(String(36), nullable=False)
    ledger_row_id: Mapped[str] = mapped_column(String(36), nullable=False)
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    method: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)    # confirmed | proposed | rejected
    matched_on: Mapped[date] = mapped_column(Date, nullable=False)     # the day the money moved
    decided_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
