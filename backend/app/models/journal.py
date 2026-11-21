"""The double-entry journal as tables (plan v11 A1.1, ADR 0001).

Until now the journal existed only as one JSON document per job
(`reports.tr_muhasebe_journal`). These tables hold the same entries, one row per
entry and one per line, so that:
- an entry that does not balance cannot be stored (CHECK on the entry totals,
  which the writer computes from the lines);
- a line is either a debit or a credit, never both, never negative;
- the trial balance, the e-Defter and the P&L can be derived by account code
  with the ORM (CLAUDE.md #4).

What is stored is what the agent *proposed*. The accountant's decisions stay in
`SMMMOnayKaydi` and are applied on read (`approved_journal.uygula`), exactly as
for the JSON. Rows are rebuilt from scratch on each run; entry ids (`kayit_id`)
are stable across runs (`double_entry.kararli_kayit_id`), so decisions still
point at the right entry.

Money is kuruş in BIGINT (CLAUDE.md conventions; migration 056 for why not int4).
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _uuid() -> str:
    return str(uuid.uuid4())


class JournalEntry(Base):
    __tablename__ = "journal_entries"
    __table_args__ = (
        UniqueConstraint("job_id", "kayit_id", name="uq_journal_entries_job_kayit"),
        Index("ix_journal_entries_org_tarih", "org_id", "tarih"),
        CheckConstraint("toplam_borc_kurus = toplam_alacak_kurus", name="ck_journal_entries_balanced"),
        CheckConstraint("toplam_borc_kurus >= 0", name="ck_journal_entries_nonneg"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    org_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # Stable per source transaction (uuid5); SMMMOnayKaydi.kayit_id points here.
    kayit_id: Mapped[str] = mapped_column(String(36), nullable=False)
    # Order within the job's journal, as the engine produced it.
    sira: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tarih: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # "islem" = the transaction's own date; "belirsiz" = a placeholder, not to be filed on.
    tarih_kaynagi: Mapped[str] = mapped_column(String(20), nullable=False, default="islem")
    aciklama: Mapped[str] = mapped_column(Text, nullable=False, default="")
    kaynak_islem_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    thp_hesap_kodu: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    onay_gerekli: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    onay_neden: Mapped[str] = mapped_column(Text, nullable=False, default="")
    kdv_durumu: Mapped[str] = mapped_column(String(20), nullable=False, default="yok")
    guven: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    authority: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    toplam_borc_kurus: Mapped[int] = mapped_column(BigInteger, nullable=False)
    toplam_alacak_kurus: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)


class JournalLine(Base):
    __tablename__ = "journal_lines"
    __table_args__ = (
        UniqueConstraint("entry_id", "sira", name="uq_journal_lines_entry_sira"),
        Index("ix_journal_lines_hesap", "hesap_kodu"),
        CheckConstraint("borc_kurus >= 0 AND alacak_kurus >= 0", name="ck_journal_lines_nonneg"),
        CheckConstraint("borc_kurus = 0 OR alacak_kurus = 0", name="ck_journal_lines_one_side"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    entry_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("journal_entries.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Order within the entry, as the engine produced it.
    sira: Mapped[int] = mapped_column(Integer, nullable=False)
    hesap_kodu: Mapped[str] = mapped_column(String(20), nullable=False)
    hesap_adi: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    borc_kurus: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    alacak_kurus: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    aciklama: Mapped[str] = mapped_column(Text, nullable=False, default="")
