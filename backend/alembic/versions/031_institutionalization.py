"""Kurumsallaşma Endeksi: institutionalization_snapshots.

Revision ID: 031_institutionalization
Revises: 030_authority_policies
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "031_institutionalization"
down_revision = "030_authority_policies"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "institutionalization_snapshots" in inspector.get_table_names():
        return

    op.create_table(
        "institutionalization_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=36), nullable=False),
        sa.Column("overall_score", sa.Integer(), nullable=False),
        sa.Column("grade", sa.String(length=2), nullable=False),
        sa.Column("dimensions", sa.JSON(), nullable=False),
        sa.Column("recommendations", sa.JSON(), nullable=False),
        sa.Column("signals", sa.JSON(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_institutionalization_snapshots_org_id",
        "institutionalization_snapshots",
        ["org_id"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "institutionalization_snapshots" not in inspector.get_table_names():
        return
    op.drop_index(
        "ix_institutionalization_snapshots_org_id",
        table_name="institutionalization_snapshots",
    )
    op.drop_table("institutionalization_snapshots")
