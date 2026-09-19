"""Add llm_call_logs table — per-call LLM egress ledger.

Revision ID: 026_llm_call_logs
Revises: 025_company_semantic_snapshots
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "026_llm_call_logs"
down_revision = "025_company_semantic_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "llm_call_logs" in inspector.get_table_names():
        return

    op.create_table(
        "llm_call_logs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=36), nullable=True),
        sa.Column("job_id", sa.String(length=64), nullable=True),
        sa.Column("task_type", sa.String(length=48), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Float(), nullable=False, server_default="0"),
        sa.Column("ok", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("from_cache", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_llm_call_logs_org_id", "llm_call_logs", ["org_id"])
    op.create_index("ix_llm_call_logs_job_id", "llm_call_logs", ["job_id"])
    op.create_index("ix_llm_call_logs_task_type", "llm_call_logs", ["task_type"])
    op.create_index("ix_llm_call_logs_model", "llm_call_logs", ["model"])
    op.create_index("ix_llm_call_logs_ok", "llm_call_logs", ["ok"])
    op.create_index("ix_llm_call_logs_created_at", "llm_call_logs", ["created_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "llm_call_logs" not in inspector.get_table_names():
        return
    for ix in (
        "ix_llm_call_logs_created_at",
        "ix_llm_call_logs_ok",
        "ix_llm_call_logs_model",
        "ix_llm_call_logs_task_type",
        "ix_llm_call_logs_job_id",
        "ix_llm_call_logs_org_id",
    ):
        op.drop_index(ix, table_name="llm_call_logs")
    op.drop_table("llm_call_logs")
