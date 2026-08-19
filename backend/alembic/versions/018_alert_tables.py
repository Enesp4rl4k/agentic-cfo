"""
018 — alert_tables: alert_history + alert_rules for Sprint M1

Creates persistent alert storage tables:
  - alert_history: permanent DB-backed alert log (replaces Redis TTL)
  - alert_rules: user-defined alert triggers

Revision ID: 018_alert_tables
Revises:     017_compliance_extended
Create Date: 2026-08-04
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision      = "018_alert_tables"
down_revision = "017_compliance_extended"
branch_labels = None
depends_on    = None


def _is_postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables    = inspector.get_table_names()

    # ── alert_rules ───────────────────────────────────────────────────────────
    if "alert_rules" not in tables:
        op.create_table(
            "alert_rules",
            sa.Column("id",         sa.String(32),  primary_key=True),
            sa.Column("org_id",     sa.String(36),  nullable=False, index=True),
            sa.Column("name",       sa.String(200), nullable=False),
            sa.Column("metric",     sa.String(100), nullable=False),   # cash_runway_months, anomaly_count_critical
            sa.Column("operator",   sa.String(10),  nullable=False),   # <, >, ==, >=
            sa.Column("threshold",  sa.Float(),     nullable=False),
            sa.Column("channels",   sa.Text(),      nullable=True),    # JSON list: ["slack", "email", "in_app"]
            sa.Column("severity",   sa.String(20),  nullable=False, server_default="warning"),
            sa.Column("enabled",    sa.Boolean(),   nullable=False, server_default="true"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.text("CURRENT_TIMESTAMP")),
        )

    # ── alert_history (permanent, replaces Redis TTL) ────────────────────────
    if "alert_history" not in tables:
        op.create_table(
            "alert_history",
            sa.Column("id",               sa.String(32),  primary_key=True),
            sa.Column("org_id",           sa.String(36),  nullable=False, index=True),
            sa.Column("rule_id",          sa.String(32),  nullable=True),   # FK to alert_rules (nullable — not all alerts have rules)
            sa.Column("message",          sa.Text(),      nullable=False),
            sa.Column("severity",         sa.String(20),  nullable=False, server_default="warning"),
            sa.Column("source",           sa.String(50),  nullable=True),   # cashflow, anomaly, kri, ...
            sa.Column("channels_sent",    sa.Text(),      nullable=True),   # JSON list
            sa.Column("acknowledged",     sa.Boolean(),   nullable=False, server_default="false"),
            sa.Column("acknowledged_by",  sa.String(200), nullable=True),
            sa.Column("acknowledged_at",  sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at",       sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        op.create_index(
            "ix_alert_history_org_severity",
            "alert_history",
            ["org_id", "severity"],
        )
        # Partial index: unacknowledged critical alerts (PostgreSQL only)
        if _is_postgresql():
            op.execute(
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_alert_history_unacked "
                "ON alert_history(org_id, acknowledged) "
                "WHERE acknowledged = FALSE"
            )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables    = inspector.get_table_names()

    if "alert_history" in tables:
        if _is_postgresql():
            op.execute("DROP INDEX IF EXISTS ix_alert_history_unacked")
        op.drop_index("ix_alert_history_org_severity", table_name="alert_history")
        op.drop_table("alert_history")

    if "alert_rules" in tables:
        op.drop_table("alert_rules")
