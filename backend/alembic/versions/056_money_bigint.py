"""Money columns become BIGINT.

Every amount is stored in kuruş as an integer, and every such column was a
32-bit INTEGER on Postgres: a single row above ₺21,474,836.47 overflows. For a
manufacturing or wholesale company a machine purchase, a quarter's VAT or a
large receivable crosses that, and the insert fails with the whole upload.

Widening only. INTEGER → BIGINT is lossless; no column or table is dropped.
SQLite stores every INTEGER as up to 8 bytes already, so it is left alone.

Revision ID: 056_money_bigint
Revises: 055_payment_plan_changes
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "056_money_bigint"
down_revision = "055_payment_plan_changes"
branch_labels = None
depends_on = None

# (table, column, nullable)
MONEY_COLUMNS: tuple[tuple[str, str, bool], ...] = (
    ("transactions", "amount_kurus", False),
    ("transactions", "kdv_kurus", True),
    ("transactions", "stopaj_kurus", True),
    ("canonical_transactions", "amount_cents", False),
    ("open_items", "amount_cents", False),
    ("open_items", "paid_cents", False),
    ("open_item_matches", "amount_cents", False),
)


def _postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _postgres():
        return
    for table, column, nullable in MONEY_COLUMNS:
        op.alter_column(
            table, column,
            type_=sa.BigInteger(), existing_type=sa.Integer(), existing_nullable=nullable,
        )


def downgrade() -> None:
    # Fails, as it should, if a value no longer fits in 32 bits.
    if not _postgres():
        return
    for table, column, nullable in MONEY_COLUMNS:
        op.alter_column(
            table, column,
            type_=sa.Integer(), existing_type=sa.BigInteger(), existing_nullable=nullable,
        )
