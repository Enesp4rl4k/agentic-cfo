"""Organisation tax identity: VKN and legal title.

Plan SMMM M1. The VKN was one global setting; each client company needs its
own, because an invoice's direction and the e-Defter owner are decided by it.
Two nullable columns; nothing changes for an organisation that sets neither.

Revision ID: 051_org_vkn
Revises: 050_org_membership
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "051_org_vkn"
down_revision = "050_org_membership"
branch_labels = None
depends_on = None

_COLUMNS = (("vkn", sa.String(11)), ("legal_title", sa.String(200)))


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "organizations" not in inspector.get_table_names():
        return
    have = {c["name"] for c in inspector.get_columns("organizations")}
    for name, type_ in _COLUMNS:
        if name not in have:
            op.add_column("organizations", sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "organizations" not in inspector.get_table_names():
        return
    have = {c["name"] for c in inspector.get_columns("organizations")}
    with op.batch_alter_table("organizations") as batch:
        for name, _ in _COLUMNS:
            if name in have:
                batch.drop_column(name)
