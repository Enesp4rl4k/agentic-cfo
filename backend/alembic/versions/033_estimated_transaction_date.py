"""Tahmin edilmiş işlem tarihini işaretle: date_is_estimated.

A transaction whose date could not be read was persisted as `datetime.now()` —
in three separate places — and from that moment nothing downstream could tell
an invented date from a real one. The date decides the accounting period, and
the period reaches the e-Defter, so a January transaction could be filed as
September with the sealed defensibility packet saying nothing was wrong.

The column stays NOT NULL: the row has to exist to be reviewed, and the
estimate is still made. What changes is that it says so.

Additive and defaulted to false, so existing rows keep meaning what they meant:
they were written before anyone was recording this, and calling them estimated
would be a claim the data does not support.

Revision ID: 033_estimated_transaction_date
Revises: 032_related_parties
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "033_estimated_transaction_date"
down_revision = "032_related_parties"
branch_labels = None
depends_on = None

_TABLES = ("transactions", "canonical_transactions")
_COLUMN = "date_is_estimated"


def _existing(inspector: sa.Inspector, table: str) -> set[str]:
    if table not in inspector.get_table_names():
        return set()
    return {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table in _TABLES:
        columns = _existing(inspector, table)
        if not columns or _COLUMN in columns:
            continue
        op.add_column(
            table,
            sa.Column(
                _COLUMN,
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table in _TABLES:
        if _COLUMN in _existing(inspector, table):
            op.drop_column(table, _COLUMN)
