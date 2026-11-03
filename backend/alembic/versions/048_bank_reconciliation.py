"""Bank reconciliation: what a ledger row is, and which movement paid which invoice.

An invoice and its bank receipt are one sale seen twice (plan v9 §K1). `basis` says
what a row rests on: book (a posting with an account), document (an invoice), or
cash (a bank movement). `open_item_matches` records settlements and proposals.
All additions; existing rows default to `cash`, and a re-run of the ledger backfill
sets the rest.

Revision ID: 048_bank_reconciliation
Revises: 047_open_items
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "048_bank_reconciliation"
down_revision = "047_open_items"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = inspector.get_table_names()
    if "canonical_transactions" in tables:
        columns = {c["name"] for c in inspector.get_columns("canonical_transactions")}
        if "basis" not in columns:
            op.add_column(
                "canonical_transactions",
                sa.Column("basis", sa.String(20), nullable=False, server_default="cash"),
            )
    if "open_items" in tables:
        columns = {c["name"] for c in inspector.get_columns("open_items")}
        if "paid_cents" not in columns:
            op.add_column(
                "open_items", sa.Column("paid_cents", sa.Integer(), nullable=False, server_default="0")
            )
    if "open_item_matches" not in tables:
        op.create_table(
            "open_item_matches",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), nullable=False),
            sa.Column("open_item_id", sa.String(36), nullable=False),
            sa.Column("ledger_row_id", sa.String(36), nullable=False),
            sa.Column("amount_cents", sa.Integer(), nullable=False),
            sa.Column("method", sa.String(30), nullable=False),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("matched_on", sa.Date(), nullable=False),
            sa.Column("decided_by", sa.String(36), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_open_item_matches_org_status", "open_item_matches", ["org_id", "status"])
        op.create_index("ix_open_item_matches_row", "open_item_matches", ["ledger_row_id"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = inspector.get_table_names()
    if "open_item_matches" in tables:
        op.drop_table("open_item_matches")
    if "open_items" in tables and "paid_cents" in {c["name"] for c in inspector.get_columns("open_items")}:
        with op.batch_alter_table("open_items") as batch:
            batch.drop_column("paid_cents")
    if "canonical_transactions" in tables and "basis" in {
        c["name"] for c in inspector.get_columns("canonical_transactions")
    }:
        with op.batch_alter_table("canonical_transactions") as batch:
            batch.drop_column("basis")
