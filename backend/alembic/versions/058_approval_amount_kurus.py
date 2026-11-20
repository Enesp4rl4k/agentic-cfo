"""The accountant's review queue holds amounts in kuruş.

`smmm_onay_kayitlari.tx_amount_try` was lira as NUMERIC(15,2), filled as
`int / 100` and served as a float — the one money column outside the kuruş
rule, and the API turned a zero into null. A BIGINT kuruş column is added and
filled from it; the old column stays (dropping it is for a person to approve)
and nothing reads it.

Revision ID: 058_approval_amount_kurus
Revises: 057_match_row_item_unique
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "058_approval_amount_kurus"
down_revision = "057_match_row_item_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("smmm_onay_kayitlari") as batch:
        batch.add_column(sa.Column("tx_amount_kurus", sa.BigInteger(), nullable=True))
    rows = sa.table(
        "smmm_onay_kayitlari",
        sa.column("tx_amount_try", sa.Numeric(15, 2)),
        sa.column("tx_amount_kurus", sa.BigInteger()),
    )
    op.execute(
        rows.update()
        .where(rows.c.tx_amount_try.isnot(None))
        .values(tx_amount_kurus=sa.cast(sa.func.round(rows.c.tx_amount_try * 100), sa.BigInteger()))
    )


def downgrade() -> None:
    with op.batch_alter_table("smmm_onay_kayitlari") as batch:
        batch.drop_column("tx_amount_kurus")
