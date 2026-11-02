"""agent_jobs.lease_expires_at — a role run that dies is noticed.

AgentJobs ran as in-process tasks with no expiry: a restart left them `running`
for ever and the page polling them waited for ever (plan v9 §K0 / §V6 S2).
Nullable: a job with no lease is one no worker has claimed.

Revision ID: 045_agent_job_lease
Revises: 044_transaction_account_code
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "045_agent_job_lease"
down_revision = "044_transaction_account_code"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "agent_jobs" not in inspector.get_table_names():
        return
    columns = {c["name"] for c in inspector.get_columns("agent_jobs")}
    if "lease_expires_at" not in columns:
        op.add_column(
            "agent_jobs", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True)
        )
        op.create_index("ix_agent_jobs_lease_expires_at", "agent_jobs", ["lease_expires_at"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "agent_jobs" not in inspector.get_table_names():
        return
    columns = {c["name"] for c in inspector.get_columns("agent_jobs")}
    if "lease_expires_at" in columns:
        op.drop_index("ix_agent_jobs_lease_expires_at", table_name="agent_jobs")
        with op.batch_alter_table("agent_jobs") as batch:
            batch.drop_column("lease_expires_at")
