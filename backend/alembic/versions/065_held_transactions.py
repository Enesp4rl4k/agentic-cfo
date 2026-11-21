"""held_transactions, transactions.currency_assumed, organizations.base_currency_confirmed_*.

Rows the extraction is unsure of (unknown or low confidence, unknown currency)
wait for a person in `held_transactions` instead of holding a whole upload or
entering the books as a guess. `currency_assumed` marks a row whose currency
was the organisation's base currency, not what the document said.
`base_currency_confirmed_at/_by` record that an owner or admin chose the base
currency: the stored value alone is only the column default.

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
    if "organizations" in tables:
        ocolumns = {c["name"] for c in inspector.get_columns("organizations")}
        if "base_currency_confirmed_at" not in ocolumns:
            op.add_column("organizations", sa.Column("base_currency_confirmed_at", sa.DateTime(timezone=True), nullable=True))
        if "base_currency_confirmed_by" not in ocolumns:
            op.add_column("organizations", sa.Column("base_currency_confirmed_by", sa.String(36), nullable=True))
    if "held_transactions" not in tables:
        op.create_table(
            "held_transactions",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("job_id", sa.String(36), sa.ForeignKey("analysis_jobs.id"), nullable=False),
            sa.Column("org_id", sa.String(36), nullable=True),
            sa.Column("row_key", sa.String(64), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(10), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("resolved_by", sa.String(36), nullable=True),
        )
        op.create_index("ix_held_transactions_job_id", "held_transactions", ["job_id"])
        op.create_index("ix_held_transactions_org_status", "held_transactions", ["org_id", "status"])
        op.create_index("ix_held_transactions_org_key", "held_transactions", ["org_id", "row_key"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = inspector.get_table_names()
    if "held_transactions" in tables:
        op.drop_table("held_transactions")   # its indexes go with it
    if "transactions" in tables and "currency_assumed" in {c["name"] for c in inspector.get_columns("transactions")}:
        op.drop_column("transactions", "currency_assumed")
    if "organizations" in tables:
        ocolumns = {c["name"] for c in inspector.get_columns("organizations")}
        for name in ("base_currency_confirmed_by", "base_currency_confirmed_at"):
            if name in ocolumns:
                op.drop_column("organizations", name)
