"""
014 — usage_events table for billing metering

Creates the usage_events table used by app.services.usage_meter.
Tracks billable actions (uploads, agent runs, connector syncs) per org per month.

Also adds billing_subscriptions table if it doesn't already exist
(was planned in PLATFORM_ARCHITECTURE.md but not in previous migrations).

Revision ID: 014_usage_events
Revises:     013_company_context_jsonb
Create Date: 2026-08-03
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision      = "014_usage_events"
down_revision = "013_company_context_jsonb"
branch_labels = None
depends_on    = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables    = inspector.get_table_names()

    # ── billing_subscriptions (idempotent) ────────────────────────────────────
    if "billing_subscriptions" not in tables:
        op.create_table(
            "billing_subscriptions",
            sa.Column("id",                      sa.String(36),  primary_key=True),
            sa.Column("org_id",                  sa.String(36),  nullable=False, unique=True, index=True),
            sa.Column("stripe_customer_id",      sa.String(100), nullable=True),
            sa.Column("stripe_subscription_id",  sa.String(100), nullable=True),
            sa.Column("plan",                    sa.String(20),  nullable=False, server_default="free"),
            sa.Column("status",                  sa.String(20),  nullable=False, server_default="active"),
            sa.Column("current_period_end",      sa.DateTime(timezone=True), nullable=True),
            sa.Column("cancel_at_period_end",    sa.Boolean(),   nullable=False, server_default="false"),
            sa.Column("created_at",              sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at",              sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        )

    # ── usage_events ──────────────────────────────────────────────────────────
    if "usage_events" not in tables:
        op.create_table(
            "usage_events",
            sa.Column("id",          sa.String(32),  primary_key=True),   # UUID hex (no dashes)
            sa.Column("org_id",      sa.String(36),  nullable=False, index=True),
            sa.Column("resource",    sa.String(50),  nullable=False),      # upload | agent_run | connector_sync
            sa.Column("quantity",    sa.Integer(),   nullable=False, server_default="1"),
            sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        # Composite index for monthly usage queries
        op.create_index(
            "ix_usage_events_org_resource_month",
            "usage_events",
            ["org_id", "resource", "recorded_at"],
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables    = inspector.get_table_names()

    if "usage_events" in tables:
        op.drop_index("ix_usage_events_org_resource_month", table_name="usage_events")
        op.drop_table("usage_events")

    # Note: we do NOT drop billing_subscriptions in downgrade to avoid data loss.
    # Drop manually if intentional.
