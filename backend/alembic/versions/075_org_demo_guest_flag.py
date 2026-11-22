"""organizations.is_demo_guest: guest-ness is a server-set flag, not inferred from a chosen slug.

`POST /org/create` lets a caller pick a slug and a description, so `demo-<12 hex>` plus the guest description
made an ordinary organisation pass as a demo guest workspace (which /demo/reset empties and the TTL cron
purges). The flag is set only by /demo/guest. Existing guest workspaces are backfilled from the same
fingerprint they were created with.

Revision ID: 075_org_demo_guest_flag
Revises: 074_materiality_smmm_brief
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "075_org_demo_guest_flag"
down_revision = "074_materiality_smmm_brief"
branch_labels = None
depends_on = None

_GUEST_DESCRIPTION = "Otomatik oluşturulmuş misafir demo çalışma alanı."


def upgrade() -> None:
    have = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("organizations")}
    if "is_demo_guest" not in have:
        op.add_column("organizations", sa.Column(
            "is_demo_guest", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.execute(
        sa.text(
            "UPDATE organizations SET is_demo_guest = :yes "
            "WHERE slug LIKE 'demo-%' AND description = :description"
        ).bindparams(sa.bindparam("yes", True), sa.bindparam("description", _GUEST_DESCRIPTION))
    )


def downgrade() -> None:
    have = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("organizations")}
    if "is_demo_guest" in have:
        op.drop_column("organizations", "is_demo_guest")
