"""
016 — agent_conflicts table for L2 Agent Negotiation

Creates agent_conflicts table to persist detected conflicts between agents.
Used by ConsensusEngine to store conflicts for frontend display + resolution.

Revision ID: 016_agent_conflicts
Revises:     015_anomaly_ml_metadata
Create Date: 2026-08-04
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision      = "016_agent_conflicts"
down_revision = "015_anomaly_ml_metadata"
branch_labels = None
depends_on    = None


def _is_postgresql() -> bool:
    bind = op.get_bind()
    return bind.dialect.name == "postgresql"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables    = inspector.get_table_names()

    if "agent_conflicts" not in tables:
        if _is_postgresql():
            from sqlalchemy.dialects.postgresql import JSONB
            claim_type = JSONB(astext_type=sa.Text())
            resolution_type = JSONB(astext_type=sa.Text())
        else:
            claim_type = sa.Text()
            resolution_type = sa.Text()

        op.create_table(
            "agent_conflicts",
            sa.Column("id",              sa.String(32),   primary_key=True),
            sa.Column("org_id",          sa.String(36),   nullable=False, index=True),
            sa.Column("topic",           sa.String(100),  nullable=False),
            sa.Column("agent_a",         sa.String(50),   nullable=False),
            sa.Column("agent_b",         sa.String(50),   nullable=False),
            sa.Column("claim_a",         claim_type,      nullable=True),
            sa.Column("claim_b",         claim_type,      nullable=True),
            sa.Column("consensus_score", sa.Float(),      nullable=True),
            sa.Column("resolution",      resolution_type, nullable=True),
            sa.Column("status",          sa.String(20),   nullable=False, server_default="open"),
            sa.Column("created_at",      sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("resolved_at",     sa.DateTime(timezone=True), nullable=True),
        )
        # Index for org+status lookups (active conflicts per org)
        op.create_index(
            "ix_agent_conflicts_org_status",
            "agent_conflicts",
            ["org_id", "status"],
        )
        # Index for topic-level queries
        op.create_index(
            "ix_agent_conflicts_org_topic",
            "agent_conflicts",
            ["org_id", "topic"],
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables    = inspector.get_table_names()

    if "agent_conflicts" in tables:
        op.drop_index("ix_agent_conflicts_org_topic", table_name="agent_conflicts")
        op.drop_index("ix_agent_conflicts_org_status", table_name="agent_conflicts")
        op.drop_table("agent_conflicts")
