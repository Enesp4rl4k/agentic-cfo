"""temporal_analysis_events: append-only analiz olay tablosu

Revision ID: 008
Revises: 007
Create Date: 2026-08-01

DDIA: append-only immutable event log.
Bu tablo sadece INSERT alir, UPDATE/DELETE olmaz.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "temporal_analysis_events",
        sa.Column("event_id",       sa.String(36),  nullable=False),
        sa.Column("org_id",         sa.String(36),  nullable=False),
        sa.Column("agent",          sa.String(50),  nullable=False),
        sa.Column("period",         sa.String(20),  nullable=False),
        sa.Column("period_type",    sa.String(20),  nullable=False, server_default="monthly"),
        sa.Column("metrics",        sa.Text,        nullable=False),   # JSON
        sa.Column("narrative",      sa.Text,        nullable=True),
        sa.Column("confidence",     sa.Float,       nullable=False, server_default="0.8"),
        sa.Column("data_source",    sa.String(50),  nullable=True),
        sa.Column("recorded_at",    sa.Float,       nullable=False),   # Unix timestamp
        sa.Column("schema_version", sa.Integer,     nullable=False, server_default="1"),
        sa.PrimaryKeyConstraint("event_id"),
    )
    # Okuma patternleri icin indexler
    op.create_index("ix_tae_org_agent",       "temporal_analysis_events", ["org_id", "agent"])
    op.create_index("ix_tae_org_recorded_at", "temporal_analysis_events", ["org_id", "recorded_at"])
    op.create_index("ix_tae_period",          "temporal_analysis_events", ["org_id", "agent", "period"])


def downgrade() -> None:
    op.drop_table("temporal_analysis_events")
