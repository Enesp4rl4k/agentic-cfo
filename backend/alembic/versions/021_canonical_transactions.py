"""canonical_transactions table

Revision ID: 021_canonical_transactions
Revises: 020
Create Date: 2026-08-19 20:45:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "021_canonical_transactions"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "canonical_transactions" in inspector.get_table_names():
        return

    op.create_table(
        "canonical_transactions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=36), nullable=False),
        sa.Column("source_type", sa.String(length=50), nullable=False),
        sa.Column("source_record_id", sa.String(length=120), nullable=False),
        sa.Column("sync_run_id", sa.String(length=36), nullable=True),
        sa.Column("transaction_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("direction", sa.String(length=20), nullable=False),
        sa.Column("category", sa.String(length=80), nullable=True),
        sa.Column("counterparty", sa.String(length=200), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["sync_run_id"], ["analysis_jobs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_canonical_transactions_org_id", "canonical_transactions", ["org_id"])
    op.create_index(
        "ix_canonical_transactions_source_type", "canonical_transactions", ["source_type"]
    )
    op.create_index(
        "ix_canonical_transactions_sync_run_id", "canonical_transactions", ["sync_run_id"]
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "canonical_transactions" not in inspector.get_table_names():
        return
    op.drop_index("ix_canonical_transactions_sync_run_id", table_name="canonical_transactions")
    op.drop_index("ix_canonical_transactions_source_type", table_name="canonical_transactions")
    op.drop_index("ix_canonical_transactions_org_id", table_name="canonical_transactions")
    op.drop_table("canonical_transactions")

