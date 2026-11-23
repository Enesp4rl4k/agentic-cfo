"""Pilot invites become redeemable (hashed token, company name); scheduler run ledger; ops state.

* `pilot_invites`: `company_name`, `token_hash` (SHA-256 of the e-mailed token, unique) and `issued_by`.
  Codes issued before this carried the secret in the clear and could never be redeemed (registration
  never read them): they stay as history and no longer work.
* `scheduled_job_runs`: one row per (job, organisation, period), unique, so a missed run can be caught up
  once and two schedulers cannot both run it.
* `ops_state`: the last backup report and other small operator facts.

Revision ID: 076_pilot_invite_job_runs
Revises: 075_org_demo_guest_flag
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "076_pilot_invite_job_runs"
down_revision = "075_org_demo_guest_flag"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    have = {c["name"] for c in inspector.get_columns("pilot_invites")}
    if "company_name" not in have:
        op.add_column("pilot_invites", sa.Column("company_name", sa.String(200), nullable=True))
    if "token_hash" not in have:
        op.add_column("pilot_invites", sa.Column("token_hash", sa.String(64), nullable=True))
        op.create_index("ix_pilot_invites_token_hash", "pilot_invites", ["token_hash"], unique=True)
    if "issued_by" not in have:
        op.add_column("pilot_invites", sa.Column("issued_by", sa.String(36), nullable=True))

    if not inspector.has_table("scheduled_job_runs"):
        op.create_table(
            "scheduled_job_runs",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("job", sa.String(60), nullable=False),
            sa.Column("org_id", sa.String(36), nullable=False),
            sa.Column("period", sa.String(40), nullable=False),
            sa.Column("status", sa.String(10), nullable=False),
            sa.Column("attempts", sa.Integer(), nullable=False),
            sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_error", sa.String(300), nullable=True),
            sa.UniqueConstraint("job", "org_id", "period", name="uq_scheduled_job_runs_job_org_period"),
        )
        op.create_index("ix_scheduled_job_runs_job", "scheduled_job_runs", ["job"])
    if not inspector.has_table("ops_state"):
        op.create_table(
            "ops_state",
            sa.Column("key", sa.String(60), primary_key=True),
            sa.Column("value", sa.Text(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("ops_state"):
        op.drop_table("ops_state")
    if inspector.has_table("scheduled_job_runs"):
        op.drop_table("scheduled_job_runs")
    have = {c["name"] for c in inspector.get_columns("pilot_invites")}
    if "token_hash" in have:
        op.drop_index("ix_pilot_invites_token_hash", table_name="pilot_invites")
        op.drop_column("pilot_invites", "token_hash")
    for column in ("issued_by", "company_name"):
        if column in have:
            op.drop_column("pilot_invites", column)
