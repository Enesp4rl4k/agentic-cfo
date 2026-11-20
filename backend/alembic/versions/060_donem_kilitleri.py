"""Closed months: one lock per organisation and month, and where a late row came from.

Plan SMMM M4. A month the accountant closed does not change; a row that belongs to it
but arrives later is written into the first open month, with its own date and the
closed period it belongs to kept beside it (`asil_tarih`, `asil_donem`). Two nullable
columns and one new table; nothing changes for an organisation that closes no month.

Revision ID: 060_donem_kilitleri
Revises: 059_money_check_constraints
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "060_donem_kilitleri"
down_revision = "059_money_check_constraints"
branch_labels = None
depends_on = None

_LEDGER = "canonical_transactions"
_COLUMNS = (
    ("asil_tarih", sa.DateTime(timezone=True)),
    ("asil_donem", sa.String(7)),
)


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "donem_kilitleri" not in insp.get_table_names():
        op.create_table(
            "donem_kilitleri",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), nullable=False),
            sa.Column("donem", sa.String(7), nullable=False),
            sa.Column("kilitleyen_user_id", sa.String(36), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("org_id", "donem", name="uq_donem_kilidi_org_donem"),
        )
        op.create_index("ix_donem_kilitleri_org_id", "donem_kilitleri", ["org_id"])
    if _LEDGER in insp.get_table_names():
        have = {c["name"] for c in insp.get_columns(_LEDGER)}
        for name, type_ in _COLUMNS:
            if name not in have:
                op.add_column(_LEDGER, sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if _LEDGER in insp.get_table_names():
        have = {c["name"] for c in insp.get_columns(_LEDGER)}
        with op.batch_alter_table(_LEDGER) as batch:
            for name, _ in _COLUMNS:
                if name in have:
                    batch.drop_column(name)
    if "donem_kilitleri" in insp.get_table_names():
        op.drop_table("donem_kilitleri")
