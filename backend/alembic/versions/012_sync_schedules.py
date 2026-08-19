"""Add sync_schedules table for DQ-5 Scheduled Sync

Revision ID: 012_sync_schedules
Revises: 011_stripe_billing
Create Date: 2026-08-01
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "012_sync_schedules"
down_revision = "011_stripe_billing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sync_schedules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("source_type", sa.String(50), nullable=False),
        sa.Column("frequency", sa.String(20), nullable=False, server_default="daily"),
        sa.Column("hour_utc", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("auto_analyze", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("notify_on_completion", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("source_config", sa.Text(), nullable=True),   # JSON
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(20), nullable=True, server_default="idle"),
        sa.Column("last_job_id", sa.String(36), nullable=True),
        sa.Column("last_row_count", sa.Integer(), nullable=True),
        sa.Column("last_health_score", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()),
    )

    op.create_index("ix_sync_schedules_org_enabled", "sync_schedules", ["org_id", "enabled"])


def downgrade() -> None:
    op.drop_index("ix_sync_schedules_org_enabled", table_name="sync_schedules")
    op.drop_table("sync_schedules")
