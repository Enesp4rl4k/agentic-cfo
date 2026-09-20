"""Connector Platform (Faz 13): connector_connections + canonical_eng_signals.

Revision ID: 027_connectors
Revises: 026_llm_call_logs
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "027_connectors"
down_revision = "026_llm_call_logs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "connector_connections" not in tables:
        op.create_table(
            "connector_connections",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("org_id", sa.String(length=36), nullable=False),
            sa.Column("connector", sa.String(length=50), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
            sa.Column("display_name", sa.String(length=160), nullable=True),
            sa.Column("config_json", sa.Text(), nullable=True),
            sa.Column("secret_enc", sa.Text(), nullable=True),
            sa.Column("watermark_cursor", sa.String(length=200), nullable=True),
            sa.Column("watermark_since", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_status", sa.String(length=20), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("last_record_count", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("org_id", "connector", name="uq_connector_conn_org_connector"),
        )
        op.create_index(
            "ix_connector_connections_org_id", "connector_connections", ["org_id"]
        )
        op.create_index(
            "ix_connector_connections_connector", "connector_connections", ["connector"]
        )

    if "canonical_eng_signals" not in tables:
        op.create_table(
            "canonical_eng_signals",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("org_id", sa.String(length=36), nullable=False),
            sa.Column("source", sa.String(length=40), nullable=False),
            sa.Column("source_record_id", sa.String(length=160), nullable=False),
            sa.Column("sync_run_id", sa.String(length=36), nullable=True),
            sa.Column("signal_type", sa.String(length=24), nullable=False),
            sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("actor", sa.String(length=160), nullable=True),
            sa.Column("title", sa.Text(), nullable=True),
            sa.Column("magnitude", sa.Integer(), nullable=True),
            sa.Column("attributes", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "org_id", "source", "source_record_id",
                name="uq_canonical_eng_org_source_record",
            ),
        )
        op.create_index(
            "ix_canonical_eng_signals_org_id", "canonical_eng_signals", ["org_id"]
        )
        op.create_index(
            "ix_canonical_eng_signals_source", "canonical_eng_signals", ["source"]
        )
        op.create_index(
            "ix_canonical_eng_signals_sync_run_id", "canonical_eng_signals", ["sync_run_id"]
        )
        op.create_index(
            "ix_canonical_eng_signals_signal_type", "canonical_eng_signals", ["signal_type"]
        )
        op.create_index(
            "ix_canonical_eng_signals_occurred_at", "canonical_eng_signals", ["occurred_at"]
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "canonical_eng_signals" in tables:
        for ix in (
            "ix_canonical_eng_signals_occurred_at",
            "ix_canonical_eng_signals_signal_type",
            "ix_canonical_eng_signals_sync_run_id",
            "ix_canonical_eng_signals_source",
            "ix_canonical_eng_signals_org_id",
        ):
            op.drop_index(ix, table_name="canonical_eng_signals")
        op.drop_table("canonical_eng_signals")

    if "connector_connections" in tables:
        for ix in (
            "ix_connector_connections_connector",
            "ix_connector_connections_org_id",
        ):
            op.drop_index(ix, table_name="connector_connections")
        op.drop_table("connector_connections")
