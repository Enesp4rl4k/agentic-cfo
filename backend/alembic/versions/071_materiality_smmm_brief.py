"""organizations.materiality_applied, organizations.briefing_to_smmm.

`materiality_applied`: the amount above which a decision needs a senior person, once an owner or admin
acknowledged the proposed value (or set their own). Null until then: nothing changes silently.
`briefing_to_smmm`: the owner's standing choice that the Monday briefing also goes to the accountant.

Revision ID: 071_materiality_smmm_brief
Revises: 070_direction_mappings
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "071_materiality_smmm_brief"
down_revision = "070_direction_mappings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("organizations", sa.Column("materiality_applied", sa.JSON(), nullable=True))
    op.add_column("organizations", sa.Column(
        "briefing_to_smmm", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("organizations") as batch:
        batch.drop_column("briefing_to_smmm")
        batch.drop_column("materiality_applied")
