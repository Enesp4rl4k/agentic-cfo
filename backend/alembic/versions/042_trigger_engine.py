"""The P4-1 trigger engine's two tables.

- trigger_definitions: stored trigger rules (the P4-0 envelope, JSON columns).
- trigger_runs: one audit row per (trigger, event) decision, with a unique
  constraint on that pair — the idempotency guard that stops a redelivered
  event from firing twice.

Revision ID: 042_trigger_engine
Revises: 041_category_rule_org
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "042_trigger_engine"
down_revision = "041_category_rule_org"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())

    if "trigger_definitions" not in tables:
        op.create_table(
            "trigger_definitions",
            sa.Column("id", sa.String(32), nullable=False),
            sa.Column("org_id", sa.String(36), nullable=False),
            sa.Column("name", sa.String(120), nullable=False),
            sa.Column("events", sa.Text(), nullable=False),
            sa.Column("condition", sa.Text(), nullable=False),
            sa.Column("action_kind", sa.String(40), nullable=False),
            sa.Column("action_params", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("cooldown_minutes", sa.Integer(), nullable=False, server_default="60"),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_trigger_definitions_org_id",
            "trigger_definitions",
            ["org_id"],
        )
        op.create_index(
            "ix_trigger_definitions_org_enabled",
            "trigger_definitions",
            ["org_id", "enabled"],
        )

    if "trigger_runs" not in tables:
        op.create_table(
            "trigger_runs",
            sa.Column("id", sa.String(32), nullable=False),
            sa.Column("org_id", sa.String(36), nullable=False),
            sa.Column("trigger_id", sa.String(32), nullable=False),
            sa.Column("event_kind", sa.String(40), nullable=False),
            sa.Column("event_ref", sa.String(120), nullable=False),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("action_kind", sa.String(40), nullable=True),
            sa.Column("action_result", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "trigger_id",
                "event_ref",
                name="uq_trigger_runs_trigger_event",
            ),
        )
        op.create_index("ix_trigger_runs_org_id", "trigger_runs", ["org_id"])
        op.create_index(
            "ix_trigger_runs_trigger_created",
            "trigger_runs",
            ["trigger_id", "created_at"],
        )


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())

    if "trigger_runs" in tables:
        op.drop_index("ix_trigger_runs_trigger_created", table_name="trigger_runs")
        op.drop_index("ix_trigger_runs_org_id", table_name="trigger_runs")
        op.drop_table("trigger_runs")

    if "trigger_definitions" in tables:
        op.drop_index(
            "ix_trigger_definitions_org_enabled", table_name="trigger_definitions"
        )
        op.drop_index("ix_trigger_definitions_org_id", table_name="trigger_definitions")
        op.drop_table("trigger_definitions")
