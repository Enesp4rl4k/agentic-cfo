"""organizations.materiality_applied, organizations.briefing_to_smmm.

`materiality_applied`: the amount above which a decision needs a senior person, once an owner or admin
acknowledged the proposed value (or set their own). Null until then: nothing changes silently.
`briefing_to_smmm`: the owner's standing choice that the Monday briefing also goes to the accountant.

`payment_plan_changes.threshold_*`: the materiality threshold in force when a change was proposed.

Revision ID: 073_materiality_smmm_brief
Revises: 072_email_verification
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "073_materiality_smmm_brief"
down_revision = "072_email_verification"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("organizations", sa.Column("materiality_applied", sa.JSON(), nullable=True))
    op.add_column("organizations", sa.Column(
        "briefing_to_smmm", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("payment_plan_changes", sa.Column("threshold_cents", sa.BigInteger(), nullable=True))
    op.add_column("payment_plan_changes", sa.Column("threshold_currency", sa.String(8), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("payment_plan_changes") as batch:
        batch.drop_column("threshold_currency")
        batch.drop_column("threshold_cents")
    with op.batch_alter_table("organizations") as batch:
        batch.drop_column("briefing_to_smmm")
        batch.drop_column("materiality_applied")
