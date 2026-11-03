"""open_items, and what a transaction's document said about payment.

`PaymentDueDate` was never read, so no cash plan could rest on a real date (plan
v9 §K1). All additions; every existing row simply has no document behind it.

Revision ID: 047_open_items
Revises: 046_ledger_columns
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "047_open_items"
down_revision = "046_ledger_columns"
branch_labels = None
depends_on = None

_TX_COLUMNS = (
    ("document_id", sa.String(64)),
    ("due_date", sa.Date()),
    ("payment_note", sa.Text()),
    ("counterparty", sa.String(300)),
)


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = inspector.get_table_names()
    if "transactions" in tables:
        columns = {c["name"] for c in inspector.get_columns("transactions")}
        for name, kind in _TX_COLUMNS:
            if name not in columns:
                op.add_column("transactions", sa.Column(name, kind, nullable=True))
    if "open_items" not in tables:
        op.create_table(
            "open_items",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), nullable=False),
            sa.Column("direction", sa.String(20), nullable=False),
            sa.Column("instrument", sa.String(20), nullable=False),
            sa.Column("document_id", sa.String(64), nullable=False),
            sa.Column("source_job_id", sa.String(36), nullable=True),
            sa.Column("counterparty", sa.String(300), nullable=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("amount_cents", sa.Integer(), nullable=False),
            sa.Column("currency", sa.String(8), nullable=False),
            sa.Column("issue_date", sa.Date(), nullable=False),
            sa.Column("due_date", sa.Date(), nullable=True),
            sa.Column("payment_note", sa.Text(), nullable=True),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("org_id", "document_id", name="uq_open_items_org_document"),
        )
        op.create_index("ix_open_items_org_status_due", "open_items", ["org_id", "status", "due_date"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = inspector.get_table_names()
    if "open_items" in tables:
        op.drop_index("ix_open_items_org_status_due", table_name="open_items")
        op.drop_table("open_items")
    if "transactions" in tables:
        columns = {c["name"] for c in inspector.get_columns("transactions")}
        with op.batch_alter_table("transactions") as batch:
            for name, _ in _TX_COLUMNS:
                if name in columns:
                    batch.drop_column(name)
