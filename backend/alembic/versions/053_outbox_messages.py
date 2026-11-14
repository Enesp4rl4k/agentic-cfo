"""The outbox: external effects keyed by what they are for, sent once.

Plan v11 C9 / A0.5; first consumer is the Monday briefing e-mail (v10 S1.3).
A new table; nothing existing changes.

Revision ID: 053_outbox_messages
Revises: 052_cash_radar_snapshots
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "053_outbox_messages"
down_revision = "052_cash_radar_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "outbox_messages" in inspector.get_table_names():
        return
    op.create_table(
        "outbox_messages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("org_id", sa.String(length=36), nullable=False),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("recipient", sa.String(length=255), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("source_ref", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )
    op.create_index("ix_outbox_messages_org_id", "outbox_messages", ["org_id"])
    op.create_index(
        "ix_outbox_messages_status_created", "outbox_messages", ["status", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_outbox_messages_status_created", table_name="outbox_messages")
    op.drop_index("ix_outbox_messages_org_id", table_name="outbox_messages")
    op.drop_table("outbox_messages")
