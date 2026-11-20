"""Proposed changes to when a payable is paid, and who decided them.

The owner's rule: a senior executive approves any change to a payment plan. One new table; nothing
changes for an organisation that never proposes a change, and no column of an existing table is touched.

Revision ID: 055_payment_plan_changes
Revises: 054_outbox_messages
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "055_payment_plan_changes"
down_revision = "054_outbox_messages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "payment_plan_changes" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "payment_plan_changes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("open_item_id", sa.String(36), nullable=False),
        sa.Column("from_date", sa.Date(), nullable=False),
        sa.Column("to_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("requested_by", sa.String(36), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_note", sa.Text(), nullable=True),
        sa.Column("decided_by", sa.String(36), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
    )
    op.create_index("ix_payment_plan_changes_org_status", "payment_plan_changes", ["org_id", "status"])
    op.create_index("ix_payment_plan_changes_item", "payment_plan_changes", ["open_item_id"])


def downgrade() -> None:
    if "payment_plan_changes" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("payment_plan_changes")
