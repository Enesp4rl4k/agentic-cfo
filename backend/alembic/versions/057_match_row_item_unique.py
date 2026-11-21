"""One match per bank row and invoice.

Two reconcile passes over the same bank row (two uploads finishing together,
or a reconcile racing a confirm) could each write a match for the same
(row, invoice) pair and each add the payment, so the invoice read paid twice.
`paid_cents` is now derived from the confirmed matches; this constraint keeps
the matches themselves from being duplicated.

Nothing is dropped or deleted. If duplicates already exist the upgrade stops
and says how many: which copy to keep is a decision for a person, not for a
migration.

Revision ID: 057_match_row_item_unique
Revises: 056_money_bigint
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "057_match_row_item_unique"
down_revision = "056_money_bigint"
branch_labels = None
depends_on = None

NAME = "uq_open_item_matches_row_item"


def upgrade() -> None:
    matches = sa.table("open_item_matches", sa.column("ledger_row_id"), sa.column("open_item_id"))
    pairs = (
        sa.select(matches.c.ledger_row_id, matches.c.open_item_id)
        .group_by(matches.c.ledger_row_id, matches.c.open_item_id)
        .having(sa.func.count() > 1)
        .subquery()
    )
    duplicates = op.get_bind().execute(sa.select(sa.func.count()).select_from(pairs)).scalar()
    if duplicates:
        raise RuntimeError(
            f"open_item_matches has {duplicates} (ledger_row_id, open_item_id) pairs recorded "
            "more than once. Resolve them (keep one row per pair), then run this migration again."
        )
    with op.batch_alter_table("open_item_matches") as batch:
        batch.create_unique_constraint(NAME, ["ledger_row_id", "open_item_id"])


def downgrade() -> None:
    with op.batch_alter_table("open_item_matches") as batch:
        batch.drop_constraint(NAME, type_="unique")
