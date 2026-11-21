"""held_transactions, and transactions.currency_assumed.

Rows the extraction is unsure of (unknown or low confidence, unknown currency)
wait for a person in `held_transactions` instead of holding a whole upload or
entering the books as a guess. `currency_assumed` marks a row whose currency
was the organisation's base currency, not what the document said.

Revision ID: 065_held_transactions
Revises: 064_decisions_table
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "065_held_transactions"
down_revision = "064_decisions_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = inspector.get_table_names()
    if "transactions" in tables:
        columns = {c["name"] for c in inspector.get_columns("transactions")}
        if "currency_assumed" not in columns:
            op.add_column(
                "transactions",
                sa.Column("currency_assumed", sa.Boolean(), nullable=False, server_default="0"),
            )
    if "held_transactions" not in tables:
        op.create_table(
            "held_transactions",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("job_id", sa.String(36), sa.ForeignKey("analysis_jobs.id"), nullable=False),
            sa.Column("org_id", sa.String(36), nullable=True),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(10), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("resolved_by", sa.String(36), nullable=True),
        )
        op.create_index("ix_held_transactions_job_id", "held_transactions", ["job_id"])
        op.create_index("ix_held_transactions_org_status", "held_transactions", ["org_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_held_transactions_org_status", table_name="held_transactions")
    op.drop_index("ix_held_transactions_job_id", table_name="held_transactions")
    op.drop_table("held_transactions")
    op.drop_column("transactions", "currency_assumed")
