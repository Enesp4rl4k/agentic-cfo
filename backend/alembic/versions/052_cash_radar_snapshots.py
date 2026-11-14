"""The radar's forecast log: one row per distinct forecast, per day.

Plan v10 O5. Grading the 4-week forecast needs the forecast made 4 weeks ago, not a
recomputation with today's knowledge. A new table; nothing existing changes.

Revision ID: 052_cash_radar_snapshots
Revises: 051_org_vkn
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "052_cash_radar_snapshots"
down_revision = "051_org_vkn"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "cash_radar_snapshots" in inspector.get_table_names():
        return
    op.create_table(
        "cash_radar_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=36), nullable=False),
        sa.Column("anchor_date", sa.Date(), nullable=False),
        sa.Column("snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "org_id", "anchor_date", "snapshot_hash", name="uq_cash_radar_snapshot_content"
        ),
    )
    op.create_index(
        "ix_cash_radar_snapshots_org_anchor",
        "cash_radar_snapshots",
        ["org_id", "anchor_date"],
    )


def downgrade() -> None:
    op.drop_index("ix_cash_radar_snapshots_org_anchor", table_name="cash_radar_snapshots")
    op.drop_table("cash_radar_snapshots")
