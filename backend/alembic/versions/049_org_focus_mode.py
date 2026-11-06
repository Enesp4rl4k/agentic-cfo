"""Organisation focus mode: a pilot company sees only the flow it is piloting.

Plan v10 §O0. One addition; every existing company keeps every screen.

Revision ID: 049_org_focus_mode
Revises: 048_bank_reconciliation
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "049_org_focus_mode"
down_revision = "048_bank_reconciliation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "organizations" not in inspector.get_table_names():
        return
    if "focus_mode" not in {c["name"] for c in inspector.get_columns("organizations")}:
        op.add_column(
            "organizations",
            sa.Column("focus_mode", sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "organizations" in inspector.get_table_names() and "focus_mode" in {
        c["name"] for c in inspector.get_columns("organizations")
    }:
        with op.batch_alter_table("organizations") as batch:
            batch.drop_column("focus_mode")
