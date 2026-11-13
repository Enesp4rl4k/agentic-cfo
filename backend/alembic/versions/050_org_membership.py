"""Organisation membership: a user may belong to several organisations.

Plan SMMM M1. An accountant's clients become organisations of their own; the
accountant is a member of each (role `smmm`) and acts in one at a time
(`users.org_id`, unchanged). Existing users get a membership row for the
organisation they are already in, with the role they already have, so nothing
changes for anyone until they join a second organisation.

Revision ID: 050_org_membership
Revises: 049_org_focus_mode
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision = "050_org_membership"
down_revision = "049_org_focus_mode"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "org_memberships" not in tables:
        op.create_table(
            "org_memberships",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "org_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("role", sa.String(20), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("user_id", "org_id", name="uq_org_membership_user_org"),
        )
        op.create_index("ix_org_memberships_user_id", "org_memberships", ["user_id"])
        op.create_index("ix_org_memberships_org_id", "org_memberships", ["org_id"])

    # Backfill: the organisation each user is in now, with the role they have.
    if "users" in tables:
        memberships = sa.table(
            "org_memberships",
            sa.column("id", sa.String),
            sa.column("user_id", sa.String),
            sa.column("org_id", sa.String),
            sa.column("role", sa.String),
            sa.column("created_at", sa.DateTime(timezone=True)),
        )
        users = sa.table(
            "users", sa.column("id", sa.String), sa.column("org_id", sa.String),
            sa.column("role", sa.String),
        )
        have = {
            (r[0], r[1])
            for r in bind.execute(sa.select(memberships.c.user_id, memberships.c.org_id))
        }
        now = datetime.now(UTC)
        rows = [
            {
                "id": str(uuid.uuid4()), "user_id": u.id, "org_id": u.org_id,
                "role": u.role, "created_at": now,
            }
            for u in bind.execute(sa.select(users.c.id, users.c.org_id, users.c.role))
            if u.org_id and (u.id, u.org_id) not in have
        ]
        if rows:
            op.bulk_insert(memberships, rows)


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "org_memberships" in inspector.get_table_names():
        op.drop_table("org_memberships")
