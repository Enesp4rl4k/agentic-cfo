"""İşlemde belgenin söylediği KDV ve stopaj: transactions.kdv_kurus / stopaj_kurus.

An e-SMM uploaded live states its fee, KDV and stopaj. The row that reached
the journal carried only the net amount, so the approval queue told the
accountant "KDV not split — no rate in the source" about a document that
stated the KDV to the kuruş, and the stopaj was not booked at all.

Both nullable, and null means something: the source did not say (a bank
line). Zero means it said "none". The journal treats them differently.

Revision ID: 035_transaction_tax_amounts
Revises: 034_job_smmm_client
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "035_transaction_tax_amounts"
down_revision = "034_job_smmm_client"
branch_labels = None
depends_on = None

_TABLE = "transactions"
_COLUMNS = ("kdv_kurus", "stopaj_kurus")


def _existing(inspector: sa.Inspector) -> set[str]:
    if _TABLE not in inspector.get_table_names():
        return set()
    return {c["name"] for c in inspector.get_columns(_TABLE)}


def upgrade() -> None:
    have = _existing(sa.inspect(op.get_bind()))
    for name in _COLUMNS:
        if name not in have:
            op.add_column(_TABLE, sa.Column(name, sa.Integer(), nullable=True))


def downgrade() -> None:
    have = _existing(sa.inspect(op.get_bind()))
    for name in _COLUMNS:
        if name in have:
            op.drop_column(_TABLE, name)
