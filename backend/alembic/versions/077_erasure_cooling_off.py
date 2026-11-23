"""Erasure cooling-off, member scope and operator initiation on org_erasure_requests.

A confirmed erasure no longer destroys at once: it is scheduled (`execute_after`) and can be cancelled until then.
The same table now carries a member-scope request (one person's account) and records who set it going.

Revision ID: 077_erasure_cooling_off
Revises: 076_pilot_invite_job_runs
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "077_erasure_cooling_off"
down_revision = "076_pilot_invite_job_runs"
branch_labels = None
depends_on = None

_TABLE = "org_erasure_requests"


def _have() -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(_TABLE)}


def upgrade() -> None:
    have = _have()
    cols = [
        sa.Column("scope", sa.String(10), nullable=False, server_default="org"),
        sa.Column("initiated_by", sa.String(10), nullable=False, server_default="owner"),
        sa.Column("verification_ref", sa.String(100), nullable=True),
        sa.Column("target_user_id", sa.String(36), nullable=True),
        sa.Column("execute_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by_hash", sa.String(64), nullable=True),
        sa.Column("blocked_reason", sa.String(40), nullable=True),
    ]
    for col in cols:
        if col.name not in have:
            op.add_column(_TABLE, col)
    indexes = {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(_TABLE)}
    if "ix_org_erasure_requests_target_user_id" not in indexes:
        op.create_index("ix_org_erasure_requests_target_user_id", _TABLE, ["target_user_id"])


def downgrade() -> None:
    have = _have()
    indexes = {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(_TABLE)}
    if "ix_org_erasure_requests_target_user_id" in indexes:
        op.drop_index("ix_org_erasure_requests_target_user_id", table_name=_TABLE)
    for name in ("blocked_reason", "cancelled_by_hash", "cancelled_at", "execute_after", "target_user_id",
                 "verification_ref", "initiated_by", "scope"):
        if name in have:
            op.drop_column(_TABLE, name)
