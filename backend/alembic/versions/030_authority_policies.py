"""Yetki Matrisi (Delegation of Authority): authority_policies.

Revision ID: 030_authority_policies
Revises: 029_defensibility_packet
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "030_authority_policies"
down_revision = "029_defensibility_packet"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "authority_policies" in inspector.get_table_names():
        return

    op.create_table(
        "authority_policies",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("rules", sa.JSON(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_authority_policies_org_id", "authority_policies", ["org_id"])
    op.create_index("ix_authority_policies_active", "authority_policies", ["active"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "authority_policies" not in inspector.get_table_names():
        return
    op.drop_index("ix_authority_policies_active", table_name="authority_policies")
    op.drop_index("ix_authority_policies_org_id", table_name="authority_policies")
    op.drop_table("authority_policies")
