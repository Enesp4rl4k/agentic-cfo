"""An amount a company is owed or owes, from a document that says so.

The ledger records money and when it was booked; a cash plan needs what is still
outstanding and when it falls due. An invoice opens an item; a matched bank
movement will close it (plan v9 §K1). `due_date` is None when the document gave
no date we could believe: unknown is reported, never guessed.
"""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import Date, DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class OpenItem(Base):
    __tablename__ = "open_items"
    __table_args__ = (
        UniqueConstraint("org_id", "document_id", name="uq_open_items_org_document"),
        Index("ix_open_items_org_status_due", "org_id", "status", "due_date"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(36), nullable=False)
    direction: Mapped[str] = mapped_column(String(20), nullable=False)      # receivable | payable
    instrument: Mapped[str] = mapped_column(String(20), nullable=False, default="invoice")
    document_id: Mapped[str] = mapped_column(String(64), nullable=False)    # e-Fatura UUID
    source_job_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    counterparty: Mapped[str | None] = mapped_column(String(300), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="TRY")
    issue_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # The document's own words: "%50 peşin, %50 45 gün sonra" means one date does
    # not cover the whole amount, and that is for a person to read.
    payment_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")  # open | settled
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
