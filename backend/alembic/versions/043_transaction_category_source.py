"""transactions.category_source — which categories a user's own rule decided.

Corrections were saved as CategoryRules but never applied to later analyses
(plan v5 §F0). Now that they are, a transaction records that its category came
from the organisation's rule ("user_rule") so the UI can say so. Nullable:
every existing row was categorised by the built-in heuristics, which is what
NULL means.

Revision ID: 043_transaction_category_source
Revises: 042_trigger_engine
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "043_transaction_category_source"
down_revision = "042_trigger_engine"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "transactions" not in inspector.get_table_names():
        return
    columns = {c["name"] for c in inspector.get_columns("transactions")}
    if "category_source" not in columns:
        op.add_column(
            "transactions", sa.Column("category_source", sa.String(20), nullable=True)
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "transactions" not in inspector.get_table_names():
        return
    columns = {c["name"] for c in inspector.get_columns("transactions")}
    if "category_source" in columns:
        with op.batch_alter_table("transactions") as batch:
            batch.drop_column("category_source")
