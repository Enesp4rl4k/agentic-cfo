"""Organisation erasure bookkeeping: requests and a hash-chained record.

KVKK Md. 7 erasure of a whole organisation is a two-step operation (request,
then owner confirmation) and leaves tamper-evident proof. Two new tables;
nothing existing changes, so downgrade simply drops them.

Revision ID: 061_org_erasure
Revises: 060_journal_tables
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "061_org_erasure"
down_revision = "060_journal_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "org_erasure_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("target_org_id", sa.String(36), nullable=True),
        sa.Column("org_hash", sa.String(64), nullable=False),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("requested_by_user_id", sa.String(36), nullable=True),
        sa.Column("requested_by_hash", sa.String(64), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_by_hash", sa.String(64), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("record_id", sa.String(36), nullable=True),
    )
    op.create_index("ix_org_erasure_requests_target_org_id", "org_erasure_requests", ["target_org_id"])
    op.create_index("ix_org_erasure_requests_org_hash", "org_erasure_requests", ["org_hash"])

    op.create_table(
        "org_erasure_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("org_hash", sa.String(64), nullable=False),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("requested_by_hash", sa.String(64), nullable=True),
        sa.Column("confirmed_by_hash", sa.String(64), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("counts", sa.JSON(), nullable=False),
        sa.Column("prev_hash", sa.String(64), nullable=False),
        sa.Column("record_hash", sa.String(64), nullable=False),
        sa.UniqueConstraint("seq", name="uq_org_erasure_records_seq"),
    )
    op.create_index("ix_org_erasure_records_org_hash", "org_erasure_records", ["org_hash"])


def downgrade() -> None:
    op.drop_index("ix_org_erasure_records_org_hash", table_name="org_erasure_records")
    op.drop_table("org_erasure_records")
    op.drop_index("ix_org_erasure_requests_org_hash", table_name="org_erasure_requests")
    op.drop_index("ix_org_erasure_requests_target_org_id", table_name="org_erasure_requests")
    op.drop_table("org_erasure_requests")
