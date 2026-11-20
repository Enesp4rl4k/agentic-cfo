"""The database checks what the code assumes about money rows.

There was no CHECK constraint anywhere. Statuses and directions were free
strings, so a misspelt one left a row in no total at all (the ledger counts
`active`, the journal files `onaylandi`), and nothing stopped a negative paid
amount. These are the values the code writes today.

Nothing is dropped or changed. If a row already breaks a rule the upgrade stops
and names the rule and the count: fixing data is a person's decision.

Revision ID: 059_money_check_constraints
Revises: 058_approval_amount_kurus
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "059_money_check_constraints"
down_revision = "058_approval_amount_kurus"
branch_labels = None
depends_on = None

# (table, name, condition) — copied, not imported, so this migration keeps
# meaning what it meant when it was written.
CHECKS: tuple[tuple[str, str, str], ...] = (
    ("open_items", "ck_open_items_direction", "direction IN ('receivable', 'payable')"),
    ("open_items", "ck_open_items_status", "status IN ('open', 'settled')"),
    ("open_items", "ck_open_items_amounts", "amount_cents >= 0 AND paid_cents >= 0"),
    ("open_item_matches", "ck_open_item_matches_status", "status IN ('confirmed', 'proposed', 'rejected')"),
    ("open_item_matches", "ck_open_item_matches_amount", "amount_cents > 0"),
    ("canonical_transactions", "ck_canonical_tx_ledger_status",
     "ledger_status IN ('active', 'possible_duplicate', 'excluded')"),
    ("canonical_transactions", "ck_canonical_tx_basis", "basis IN ('book', 'document', 'cash')"),
    ("smmm_onay_kayitlari", "ck_smmm_onay_durum",
     "durum IN ('bekliyor', 'onaylandi', 'duzeltildi', 'reddedildi')"),
)


def _violations(table: str, condition: str) -> int:
    # NOT (condition) is NULL for a NULL column; those columns are NOT NULL here.
    rows = sa.table(table)
    query = sa.select(sa.func.count()).select_from(rows).where(sa.not_(sa.literal_column(f"({condition})")))
    return int(op.get_bind().execute(query).scalar() or 0)


def upgrade() -> None:
    broken = [(name, n) for table, name, cond in CHECKS if (n := _violations(table, cond))]
    if broken:
        raise RuntimeError(
            "Rows break the new checks; fix them, then run this migration again: "
            + ", ".join(f"{name}={n}" for name, n in broken)
        )
    for table, name, condition in CHECKS:
        with op.batch_alter_table(table) as batch:
            batch.create_check_constraint(name, condition)


def downgrade() -> None:
    for table, name, _ in reversed(CHECKS):
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(name, type_="check")
