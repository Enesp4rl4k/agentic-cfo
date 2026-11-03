"""canonical_transactions becomes the company ledger.

Every analysis was an island (plan v9 §K1 / §V5 F1). These columns let a row say
which upload brought it, which account it was posted to, and whether it is
counted: `active`, or `possible_duplicate` until a person decides, or `excluded`
after they say it repeats money already there. Existing rows are `active`.

Revision ID: 046_ledger_columns
Revises: 045_agent_job_lease
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "046_ledger_columns"
down_revision = "045_agent_job_lease"
branch_labels = None
depends_on = None

_COLUMNS = (
    ("source_job_id", sa.String(36)),
    ("account_code", sa.String(20)),
    ("duplicate_of", sa.String(36)),
)


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "canonical_transactions" not in inspector.get_table_names():
        return
    columns = {c["name"] for c in inspector.get_columns("canonical_transactions")}
    for name, kind in _COLUMNS:
        if name not in columns:
            op.add_column("canonical_transactions", sa.Column(name, kind, nullable=True))
    if "ledger_status" not in columns:
        op.add_column(
            "canonical_transactions",
            sa.Column("ledger_status", sa.String(20), nullable=False, server_default="active"),
        )
        op.create_index(
            "ix_canonical_transactions_ledger_status", "canonical_transactions", ["ledger_status"]
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "canonical_transactions" not in inspector.get_table_names():
        return
    columns = {c["name"] for c in inspector.get_columns("canonical_transactions")}
    if "ledger_status" in columns:
        op.drop_index("ix_canonical_transactions_ledger_status", table_name="canonical_transactions")
    with op.batch_alter_table("canonical_transactions") as batch:
        for name in ("source_job_id", "account_code", "duplicate_of", "ledger_status"):
            if name in columns:
                batch.drop_column(name)
