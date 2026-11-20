"""The double-entry journal as tables: journal_entries and journal_lines.

Plan v11 A1.1, ADR 0001. The journal lived only as one JSON document per job
(reports.tr_muhasebe_journal). These tables hold the same entries so that an
unbalanced entry cannot be stored and the trial balance can be derived by account
code. Two new tables; nothing existing changes, so downgrade simply drops them.

Revision ID: 060_journal_tables
Revises: 059_money_check_constraints
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "060_journal_tables"
down_revision = "059_money_check_constraints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "journal_entries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "job_id", sa.String(36),
            sa.ForeignKey("analysis_jobs.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("org_id", sa.String(36), nullable=True),
        sa.Column("kayit_id", sa.String(36), nullable=False),
        sa.Column("sira", sa.Integer(), nullable=False),
        sa.Column("tarih", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tarih_kaynagi", sa.String(20), nullable=False),
        sa.Column("aciklama", sa.Text(), nullable=False),
        sa.Column("kaynak_islem_id", sa.String(64), nullable=False),
        sa.Column("thp_hesap_kodu", sa.String(10), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("onay_gerekli", sa.Boolean(), nullable=False),
        sa.Column("onay_neden", sa.Text(), nullable=False),
        sa.Column("kdv_durumu", sa.String(20), nullable=False),
        sa.Column("guven", sa.JSON(), nullable=True),
        sa.Column("authority", sa.JSON(), nullable=True),
        sa.Column("toplam_borc_kurus", sa.BigInteger(), nullable=False),
        sa.Column("toplam_alacak_kurus", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("job_id", "kayit_id", name="uq_journal_entries_job_kayit"),
        sa.CheckConstraint("toplam_borc_kurus = toplam_alacak_kurus", name="ck_journal_entries_balanced"),
        sa.CheckConstraint("toplam_borc_kurus >= 0", name="ck_journal_entries_nonneg"),
    )
    op.create_index("ix_journal_entries_job_id", "journal_entries", ["job_id"])
    op.create_index("ix_journal_entries_org_tarih", "journal_entries", ["org_id", "tarih"])

    op.create_table(
        "journal_lines",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "entry_id", sa.String(36),
            sa.ForeignKey("journal_entries.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("sira", sa.Integer(), nullable=False),
        sa.Column("hesap_kodu", sa.String(20), nullable=False),
        sa.Column("hesap_adi", sa.String(200), nullable=False),
        sa.Column("borc_kurus", sa.BigInteger(), nullable=False),
        sa.Column("alacak_kurus", sa.BigInteger(), nullable=False),
        sa.Column("aciklama", sa.Text(), nullable=False),
        sa.UniqueConstraint("entry_id", "sira", name="uq_journal_lines_entry_sira"),
        sa.CheckConstraint("borc_kurus >= 0 AND alacak_kurus >= 0", name="ck_journal_lines_nonneg"),
        sa.CheckConstraint("borc_kurus = 0 OR alacak_kurus = 0", name="ck_journal_lines_one_side"),
    )
    op.create_index("ix_journal_lines_entry_id", "journal_lines", ["entry_id"])
    op.create_index("ix_journal_lines_hesap", "journal_lines", ["hesap_kodu"])


def downgrade() -> None:
    op.drop_index("ix_journal_lines_hesap", table_name="journal_lines")
    op.drop_index("ix_journal_lines_entry_id", table_name="journal_lines")
    op.drop_table("journal_lines")
    op.drop_index("ix_journal_entries_org_tarih", table_name="journal_entries")
    op.drop_index("ix_journal_entries_job_id", table_name="journal_entries")
    op.drop_table("journal_entries")
