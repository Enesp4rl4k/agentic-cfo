"""Data exports, notice acceptances, retention runs, and the organisation's retention choices.

Revision ID: 078_privacy_records
Revises: 077_erasure_cooling_off
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "078_privacy_records"
down_revision = "077_erasure_cooling_off"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    have = _tables()
    if "data_exports" not in have:
        op.create_table(
            "data_exports",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), nullable=False),
            sa.Column("requested_by", sa.String(36), nullable=False),
            sa.Column("status", sa.String(12), nullable=False),
            sa.Column("file_path", sa.String(1000), nullable=True),
            sa.Column("size_bytes", sa.Integer(), nullable=True),
            sa.Column("summary", sa.JSON(), nullable=True),
            sa.Column("error_code", sa.String(30), nullable=True),
            sa.Column("downloads", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("ready_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_data_exports_org_id", "data_exports", ["org_id"])
        op.create_index("ix_data_exports_org_status", "data_exports", ["org_id", "status"])
    if "terms_acceptances" not in have:
        op.create_table(
            "terms_acceptances",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.String(36), nullable=False),
            sa.Column("document", sa.String(20), nullable=False),
            sa.Column("version", sa.String(40), nullable=False),
            sa.Column("source", sa.String(20), nullable=False),
            sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_terms_acceptances_user_id", "terms_acceptances", ["user_id"])
        op.create_index("ix_terms_acceptances_user_document", "terms_acceptances", ["user_id", "document"])
    if "retention_runs" not in have:
        op.create_table(
            "retention_runs",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("dry_run", sa.Boolean(), nullable=False),
            sa.Column("scope", sa.String(64), nullable=False),
            sa.Column("organisations", sa.Integer(), nullable=False),
            sa.Column("policy", sa.JSON(), nullable=False),
            sa.Column("counts", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(12), nullable=False),
        )
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("organizations")}
    if "retention_policy" not in cols:
        op.add_column("organizations", sa.Column("retention_policy", sa.JSON(), nullable=True))


def downgrade() -> None:
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("organizations")}
    if "retention_policy" in cols:
        op.drop_column("organizations", "retention_policy")
    have = _tables()
    for name in ("retention_runs", "terms_acceptances", "data_exports"):
        if name in have:
            op.drop_table(name)
