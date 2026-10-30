"""transactions.account_code — the Tekdüzen Hesap Planı account a row was posted to.

Logo/Mikro/Netsis exports and the e-Defter name the account of every posting,
and the account says whether a row is revenue, an expense or a balance-sheet
movement. The column was never read: categories came from keywords and a
salary row on a sales account became revenue (plan v8 §A1). Nullable: a bank
line or a receipt has no account, which is what NULL means.

Revision ID: 044_transaction_account_code
Revises: 043_transaction_category_source
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "044_transaction_account_code"
down_revision = "043_transaction_category_source"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "transactions" not in inspector.get_table_names():
        return
    columns = {c["name"] for c in inspector.get_columns("transactions")}
    if "account_code" not in columns:
        op.add_column(
            "transactions", sa.Column("account_code", sa.String(20), nullable=True)
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "transactions" not in inspector.get_table_names():
        return
    columns = {c["name"] for c in inspector.get_columns("transactions")}
    if "account_code" in columns:
        with op.batch_alter_table("transactions") as batch:
            batch.drop_column("account_code")
