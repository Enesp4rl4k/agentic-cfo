"""Durable Runs (Faz 14): agent_runs ledger.

Revision ID: 028_agent_runs
Revises: 027_connectors
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "028_agent_runs"
down_revision = "027_connectors"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "agent_runs" in inspector.get_table_names():
        return

    op.create_table(
        "agent_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=36), nullable=True),
        sa.Column("pipeline", sa.String(length=40), nullable=False),
        sa.Column("job_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="running"),
        sa.Column("current_node", sa.String(length=60), nullable=True),
        sa.Column("node_history", sa.JSON(), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("result_ref", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_runs_org_id", "agent_runs", ["org_id"])
    op.create_index("ix_agent_runs_pipeline", "agent_runs", ["pipeline"])
    op.create_index("ix_agent_runs_job_id", "agent_runs", ["job_id"])
    op.create_index("ix_agent_runs_status", "agent_runs", ["status"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "agent_runs" not in inspector.get_table_names():
        return
    for ix in (
        "ix_agent_runs_status",
        "ix_agent_runs_job_id",
        "ix_agent_runs_pipeline",
        "ix_agent_runs_org_id",
    ):
        op.drop_index(ix, table_name="agent_runs")
    op.drop_table("agent_runs")
