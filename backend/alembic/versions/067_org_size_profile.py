"""Company size input on the organisation (size answers, confirmed profile, focus-mode choice).

All columns are nullable (or default false), so every existing company is unchanged.
`focus_mode_explicit` is back-filled from `focus_mode`: a company whose focus mode is
already on had it switched on by a person, and a size profile must never undo that.

Revision ID: 067_org_size_profile
Revises: 066_counterparty_aliases
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "067_org_size_profile"
down_revision = "066_counterparty_aliases"
branch_labels = None
depends_on = None

_COLUMNS = (
    "size_profile", "monthly_outflow_band", "headcount_band", "has_inhouse_finance",
    "size_profile_source", "size_profile_set_at", "size_profile_set_by",
)


def upgrade() -> None:
    op.add_column("organizations", sa.Column(
        "focus_mode_explicit", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("organizations", sa.Column("size_profile", sa.String(10), nullable=True))
    op.add_column("organizations", sa.Column("monthly_outflow_band", sa.String(20), nullable=True))
    op.add_column("organizations", sa.Column("headcount_band", sa.String(20), nullable=True))
    op.add_column("organizations", sa.Column("has_inhouse_finance", sa.Boolean(), nullable=True))
    op.add_column("organizations", sa.Column("size_profile_source", sa.String(24), nullable=True))
    op.add_column("organizations", sa.Column("size_profile_set_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("organizations", sa.Column("size_profile_set_by", sa.String(36), nullable=True))
    organizations = sa.table(
        "organizations", sa.column("focus_mode", sa.Boolean), sa.column("focus_mode_explicit", sa.Boolean))
    op.execute(
        organizations.update().where(organizations.c.focus_mode.is_(True)).values(focus_mode_explicit=True))


def downgrade() -> None:
    with op.batch_alter_table("organizations") as batch:
        for name in (*reversed(_COLUMNS), "focus_mode_explicit"):
            batch.drop_column(name)
