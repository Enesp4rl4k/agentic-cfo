"""sync_runs table + canonical idempotency

Revision ID: 022_sync_runs_and_canonical_idempotency
Revises: 021_canonical_transactions
Create Date: 2026-08-19 21:10:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "022_sync_runs_and_canonical_idempotency"
down_revision = "021_canonical_transactions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "sync_runs" not in inspector.get_table_names():
        op.create_table(
            "sync_runs",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("org_id", sa.String(length=36), nullable=False),
            sa.Column("schedule_id", sa.String(length=36), nullable=True),
            sa.Column("provider", sa.String(length=50), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("row_count_raw", sa.Integer(), nullable=False),
            sa.Column("row_count_canonical", sa.Integer(), nullable=False),
            sa.Column("quality_score", sa.Float(), nullable=True),
            sa.Column("triggered_job_id", sa.String(length=36), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_sync_runs_org_id", "sync_runs", ["org_id"])
        op.create_index("ix_sync_runs_provider", "sync_runs", ["provider"])
        op.create_index("ix_sync_runs_schedule_id", "sync_runs", ["schedule_id"])
        op.create_index("ix_sync_runs_triggered_job_id", "sync_runs", ["triggered_job_id"])

    # canonical_transactions constraints/foreign key hardening
    columns = {c["name"] for c in inspector.get_columns("canonical_transactions")}
    if "sync_run_id" in columns:
        # add uniqueness for idempotency
        unique_names = {u["name"] for u in inspector.get_unique_constraints("canonical_transactions")}
        if "uq_canonical_tx_org_source_record" not in unique_names:
            op.create_unique_constraint(
                "uq_canonical_tx_org_source_record",
                "canonical_transactions",
                ["org_id", "source_type", "source_record_id"],
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "canonical_transactions" in inspector.get_table_names():
        unique_names = {u["name"] for u in inspector.get_unique_constraints("canonical_transactions")}
        if "uq_canonical_tx_org_source_record" in unique_names:
            op.drop_constraint(
                "uq_canonical_tx_org_source_record",
                "canonical_transactions",
                type_="unique",
            )

    if "sync_runs" in inspector.get_table_names():
        op.drop_index("ix_sync_runs_triggered_job_id", table_name="sync_runs")
        op.drop_index("ix_sync_runs_schedule_id", table_name="sync_runs")
        op.drop_index("ix_sync_runs_provider", table_name="sync_runs")
        op.drop_index("ix_sync_runs_org_id", table_name="sync_runs")
        op.drop_table("sync_runs")

