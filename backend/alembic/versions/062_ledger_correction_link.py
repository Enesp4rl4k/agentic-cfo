"""Category corrections on closed months: the link to the corrected row, and kept overrides.

`canonical_transactions.corrects_id` marks a correction row (a reversal or a corrected
row booked in the first open month) and points at the row it corrects, so readers can
tell money from reclassification without parsing ids. `category_overrides` remembers a
person's correction of one row by its ledger identity, so a rerun does not undo it.
One nullable column, one index, one new table; downgrade drops them.

Revision ID: 062_ledger_correction_link
Revises: 061_donem_kilitleri
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "062_ledger_correction_link"
down_revision = "061_donem_kilitleri"
branch_labels = None
depends_on = None

_LEDGER = "canonical_transactions"
_INDEX = "ix_canonical_transactions_corrects_id"


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    tables = insp.get_table_names()
    if _LEDGER in tables and "corrects_id" not in {c["name"] for c in insp.get_columns(_LEDGER)}:
        op.add_column(_LEDGER, sa.Column("corrects_id", sa.String(36), nullable=True))
        op.create_index(_INDEX, _LEDGER, ["corrects_id"])
    if "category_overrides" not in tables:
        op.create_table(
            "category_overrides",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), nullable=False),
            sa.Column("source_record_id", sa.String(120), nullable=False),
            sa.Column("category", sa.String(40), nullable=False),
            sa.Column("user_id", sa.String(36), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("org_id", "source_record_id", name="uq_category_override_org_record"),
        )
        op.create_index("ix_category_overrides_org_id", "category_overrides", ["org_id"])


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    tables = insp.get_table_names()
    if "category_overrides" in tables:
        op.drop_table("category_overrides")
    if _LEDGER in tables and "corrects_id" in {c["name"] for c in insp.get_columns(_LEDGER)}:
        op.drop_index(_INDEX, table_name=_LEDGER)
        with op.batch_alter_table(_LEDGER) as batch:
            batch.drop_column("corrects_id")
