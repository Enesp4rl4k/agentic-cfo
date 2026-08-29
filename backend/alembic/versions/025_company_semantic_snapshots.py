"""Add company_semantic_snapshots table.

Revision ID: 025_company_semantic_snapshots
Revises: 024_org_international_locale
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "025_company_semantic_snapshots"
down_revision = "024_org_international_locale"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "company_semantic_snapshots" in inspector.get_table_names():
        return

    op.create_table(
        "company_semantic_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=36), nullable=False),
        sa.Column("period_key", sa.String(length=64), nullable=False),
        sa.Column("period_start", sa.String(length=32), nullable=True),
        sa.Column("period_end", sa.String(length=32), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="USD"),
        sa.Column("locale", sa.String(length=16), nullable=False, server_default="en-US"),
        sa.Column("schema_version", sa.String(length=16), nullable=False, server_default="1.0.0"),
        sa.Column("metrics_json", sa.Text(), nullable=False),
        sa.Column("drivers_json", sa.Text(), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=False),
        sa.Column("brief_json", sa.Text(), nullable=True),
        sa.Column("source_job_ids", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "period_key", name="uq_semantic_org_period"),
    )
    op.create_index(
        "ix_company_semantic_snapshots_org_id",
        "company_semantic_snapshots",
        ["org_id"],
    )
    op.create_index(
        "ix_company_semantic_snapshots_period_key",
        "company_semantic_snapshots",
        ["period_key"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "company_semantic_snapshots" not in inspector.get_table_names():
        return
    op.drop_index("ix_company_semantic_snapshots_period_key", table_name="company_semantic_snapshots")
    op.drop_index("ix_company_semantic_snapshots_org_id", table_name="company_semantic_snapshots")
    op.drop_table("company_semantic_snapshots")
