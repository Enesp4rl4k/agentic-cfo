"""SMMM Defensibility Packet (differentiator #4): defensibility_packets.

Revision ID: 029_defensibility_packet
Revises: 028_agent_runs
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "029_defensibility_packet"
down_revision = "028_agent_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "defensibility_packets" in inspector.get_table_names():
        return

    op.create_table(
        "defensibility_packets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=36), nullable=True),
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("period", sa.String(length=20), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="draft"),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("summary", sa.JSON(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("smmm_statement", sa.Text(), nullable=True),
        sa.Column("finalized_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "job_id", name="uq_defensibility_org_job"),
    )
    op.create_index("ix_defensibility_packets_org_id", "defensibility_packets", ["org_id"])
    op.create_index("ix_defensibility_packets_job_id", "defensibility_packets", ["job_id"])
    op.create_index("ix_defensibility_packets_period", "defensibility_packets", ["period"])
    op.create_index("ix_defensibility_packets_status", "defensibility_packets", ["status"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "defensibility_packets" not in inspector.get_table_names():
        return
    for ix in (
        "ix_defensibility_packets_status",
        "ix_defensibility_packets_period",
        "ix_defensibility_packets_job_id",
        "ix_defensibility_packets_org_id",
    ):
        op.drop_index(ix, table_name="defensibility_packets")
    op.drop_table("defensibility_packets")
