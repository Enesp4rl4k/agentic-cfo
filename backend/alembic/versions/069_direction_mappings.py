"""direction_mappings: a statement format's direction, answered once per organisation.

A file whose amounts' direction cannot be placed waits for one answer for the whole file;
the answer is remembered per organisation and header signature and can be revoked.

Revision ID: 069_direction_mappings
Revises: 068_held_transactions
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "069_direction_mappings"
down_revision = "068_held_transactions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "direction_mappings" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "direction_mappings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("signature", sa.String(32), nullable=False),
        sa.Column("reason", sa.String(24), nullable=False),
        sa.Column("answer", sa.String(16), nullable=False),
        sa.Column("columns", sa.String(500), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", sa.String(36), nullable=True),
    )
    op.create_index("ix_direction_mappings_org_sig", "direction_mappings", ["org_id", "signature"])


def downgrade() -> None:
    if "direction_mappings" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("direction_mappings")  # its index goes with it
