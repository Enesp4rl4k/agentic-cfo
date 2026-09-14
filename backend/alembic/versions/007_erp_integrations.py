"""erp_integrations: ERP/muhasebe yazılımı entegrasyon tablolari

Revision ID: 007
Revises: 006
Create Date: 2026-08-01
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── erp_integrations ──────────────────────────────────────────────────────
    op.create_table(
        "erp_integrations",
        sa.Column("id",                   sa.String(36),  nullable=False),
        sa.Column("org_id",               sa.String(36),  nullable=False),
        sa.Column("provider",             sa.String(50),  nullable=False),
        sa.Column("display_name",         sa.String(100), nullable=True),
        sa.Column("status",               sa.String(20),  nullable=False, server_default="pending"),
        sa.Column("access_token_enc",     sa.Text,        nullable=True),
        sa.Column("refresh_token_enc",    sa.Text,        nullable=True),
        sa.Column("token_expires_at",     sa.DateTime(timezone=True), nullable=True),
        sa.Column("scopes",               sa.Text,        nullable=True),
        sa.Column("config_enc",           sa.Text,        nullable=True),
        sa.Column("last_sync_at",         sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_status",     sa.String(20),  nullable=True),
        sa.Column("last_sync_count",      sa.Integer,     nullable=True),
        sa.Column("last_error",           sa.Text,        nullable=True),
        sa.Column("next_sync_at",         sa.DateTime(timezone=True), nullable=True),
        sa.Column("auto_sync_enabled",    sa.Boolean(),   nullable=False, server_default="1"),
        sa.Column("sync_interval_hours",  sa.Integer,     nullable=False, server_default="24"),
        sa.Column("connected_at",         sa.DateTime(timezone=True), nullable=True),
        sa.Column("disconnected_at",      sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at",           sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at",           sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_erp_integrations_org_id",  "erp_integrations", ["org_id"])
    op.create_index("ix_erp_integrations_provider", "erp_integrations", ["provider"])
    op.create_index("ix_erp_integrations_status",   "erp_integrations", ["status"])

    # ── erp_sync_logs ──────────────────────────────────────────────────────────
    op.create_table(
        "erp_sync_logs",
        sa.Column("id",                    sa.String(36),  nullable=False),
        sa.Column("integration_id",        sa.String(36),  nullable=False),
        sa.Column("org_id",                sa.String(36),  nullable=False),
        sa.Column("provider",              sa.String(50),  nullable=False),
        sa.Column("status",                sa.String(20),  nullable=False),
        sa.Column("transactions_synced",   sa.Integer,     nullable=False, server_default="0"),
        sa.Column("transactions_skipped",  sa.Integer,     nullable=False, server_default="0"),
        sa.Column("error_message",         sa.Text,        nullable=True),
        sa.Column("triggered_cfo_job_id",  sa.String(36),  nullable=True),
        sa.Column("started_at",            sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at",           sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_seconds",      sa.Integer,     nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["integration_id"], ["erp_integrations.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_erp_sync_logs_integration_id", "erp_sync_logs", ["integration_id"])
    op.create_index("ix_erp_sync_logs_org_id",         "erp_sync_logs", ["org_id"])


def downgrade() -> None:
    op.drop_table("erp_sync_logs")
    op.drop_table("erp_integrations")
