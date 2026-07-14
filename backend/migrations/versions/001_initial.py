"""Initial schema — all tables

Revision ID: 001_initial
Revises:
Create Date: 2026-07-14

Creates: analysis_jobs, transactions, reports, category_rules
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSON

revision = "001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── analysis_jobs ─────────────────────────────────────────────────────────
    op.create_table(
        "analysis_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("filename", sa.String(500), nullable=False),
        sa.Column("file_path", sa.String(1000), nullable=False),
        sa.Column("file_type", sa.String(10), nullable=False),
        sa.Column("logs", JSON, nullable=True),
        sa.Column("min_confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("awaiting_review", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ── transactions ──────────────────────────────────────────────────────────
    op.create_table(
        "transactions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "job_id",
            sa.String(36),
            sa.ForeignKey("analysis_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("amount_kurus", sa.Integer, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="TRY"),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("vendor", sa.String(200), nullable=True),
        sa.Column("transaction_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_text", sa.Text, nullable=True),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_transactions_job_id", "transactions", ["job_id"])

    # ── reports ───────────────────────────────────────────────────────────────
    op.create_table(
        "reports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "job_id",
            sa.String(36),
            sa.ForeignKey("analysis_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("report_type", sa.String(20), nullable=False),
        sa.Column("report_format", sa.String(10), nullable=False),
        sa.Column("file_path", sa.String(1000), nullable=True),
        sa.Column("data", JSON, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_reports_job_id", "reports", ["job_id"])

    # ── category_rules ────────────────────────────────────────────────────────
    op.create_table(
        "category_rules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("vendor_match", sa.String(200), nullable=True),
        sa.Column("keyword_match", sa.String(200), nullable=True),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("apply_always", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("hit_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_category_rules_vendor_match", "category_rules", ["vendor_match"])
    op.create_index("ix_category_rules_keyword_match", "category_rules", ["keyword_match"])


def downgrade() -> None:
    op.drop_table("category_rules")
    op.drop_table("reports")
    op.drop_table("transactions")
    op.drop_table("analysis_jobs")
