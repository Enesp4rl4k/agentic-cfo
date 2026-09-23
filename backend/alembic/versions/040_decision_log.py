"""Decision ledger — the closed loop decision → expectation → outcome.

Revision ID: 040_decision_log
Revises: 039_job_lease
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "040_decision_log"
down_revision = "039_job_lease"
branch_labels = None
depends_on = None

_INDEXES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ix_decision_logs_org_id", ("org_id",)),
    ("ix_decision_logs_job_id", ("job_id",)),
    ("ix_decision_logs_status", ("status",)),
)


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "decision_logs" in inspector.get_table_names():
        return

    op.create_table(
        "decision_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=True),
        sa.Column(
            "job_id",
            sa.String(36),
            sa.ForeignKey("analysis_jobs.id"),
            nullable=False,
        ),
        sa.Column("topic", sa.String(300), nullable=False),
        sa.Column("chosen_option_id", sa.String(50), nullable=False),
        sa.Column("chosen_option_label", sa.String(200), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("expected", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("actual", sa.JSON(), nullable=True),
        sa.Column("variance", sa.JSON(), nullable=True),
        sa.Column("outcome_note", sa.Text(), nullable=True),
        sa.Column("measured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    for name, columns in _INDEXES:
        op.create_index(name, "decision_logs", list(columns))


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "decision_logs" not in inspector.get_table_names():
        return
    existing = {ix["name"] for ix in inspector.get_indexes("decision_logs")}
    for name, _columns in _INDEXES:
        if name in existing:
            op.drop_index(name, table_name="decision_logs")
    op.drop_table("decision_logs")
