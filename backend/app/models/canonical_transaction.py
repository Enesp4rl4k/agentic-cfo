from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.elements import ColumnElement

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class CanonicalTransaction(Base):
    """
    Source-agnostic transaction contract used by the data plane.

    All connectors should normalize into this structure so downstream
    agents do not need provider-specific mapping logic.
    """

    __tablename__ = "canonical_transactions"
    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "source_type",
            "source_record_id",
            name="uq_canonical_tx_org_source_record",
        ),
        # The semantic rebuild reads by exactly this pair; single-column
        # indexes left it scanning (migration 039 creates it too, so old
        # databases and fresh create_all ones agree).
        Index("ix_canonical_transactions_org_date", "org_id", "transaction_date"),
        # Migration 059. A misspelt status would leave a row in no total at all.
        CheckConstraint(
            "ledger_status IN ('active', 'possible_duplicate', 'excluded')",
            name="ck_canonical_tx_ledger_status",
        ),
        CheckConstraint("basis IN ('book', 'document', 'cash')", name="ck_canonical_tx_basis"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    org_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    source_record_id: Mapped[str] = mapped_column(String(120), nullable=False)
    sync_run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("sync_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )

    transaction_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # See Transaction.date_is_estimated — same reason, same rule.
    date_is_estimated: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="0"
    )
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="TRY")
    direction: Mapped[str] = mapped_column(String(20), nullable=False, default="expense")
    category: Mapped[str | None] = mapped_column(String(80), nullable=True)
    counterparty: Mapped[str | None] = mapped_column(String(200), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # The company ledger (app/services/ledger.py).
    source_job_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    account_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # active | possible_duplicate (a person decides; not counted until then) | excluded
    ledger_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active", index=True
    )
    duplicate_of: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # What the row rests on: book (a posting with an account), document (an
    # invoice) or cash (a bank movement). One sale can appear as a document and as
    # cash; they are two views of the money, never duplicates of each other.
    basis: Mapped[str] = mapped_column(String(20), nullable=False, default="cash", server_default="cash")
    # A row that belongs to a month the accountant closed but arrived afterwards is
    # written into the first open month (`transaction_date`); its own date and the
    # closed period it belongs to are kept here (services/donem_kilidi.py).
    asil_tarih: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    asil_donem: Mapped[str | None] = mapped_column(String(7), nullable=True)
    # A row written by a category correction on a closed month (services/ledger_correction.py)
    # points at the row it corrects. It moves money between categories in the first open
    # month and is NOT money: every reader that counts, sums or detects by amount filters
    # `money_rows()`; only the by-category profit view reads these, through the original.
    corrects_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


def money_rows() -> ColumnElement[bool]:
    """The one predicate for "a row that is money": not a closed-month correction row.

    Every aggregate, count, detector and matcher over `canonical_transactions` that does
    not read categories adds this, so a correction can never create or change an amount.
    """
    return CanonicalTransaction.corrects_id.is_(None)
