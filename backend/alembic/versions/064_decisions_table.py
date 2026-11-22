"""The decision record: one append-only table for who decided what, when, on which evidence.

Plan v11 C4 / A1.6. Adds `decisions`; nothing existing changes, so downgrade drops it.
`kind` is text, not a database enum, so a new kind needs no migration. The two check
constraints hold what the database can know on its own: `decided_via` is one of three
values and `rule_id` is present exactly when a rule decided. Whether a human decision
has a `decided_by` is checked by the service, not here, because organisation erasure
may later null the person while keeping the row.

Revision ID: 064_decisions_table
Revises: 063_ledger_correction_link
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "064_decisions_table"
down_revision = "063_ledger_correction_link"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "decisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("target_type", sa.String(40), nullable=False),
        sa.Column("target_id", sa.String(120), nullable=False),
        sa.Column("outcome", sa.String(60), nullable=False),
        sa.Column("decided_by", sa.String(36), nullable=True),
        sa.Column("decided_via", sa.String(10), nullable=False),
        sa.Column("rule_id", sa.String(36), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("before", sa.JSON(), nullable=True),
        sa.Column("after", sa.JSON(), nullable=True),
        sa.Column("supersedes_id", sa.String(36), sa.ForeignKey("decisions.id"), nullable=True),
        sa.CheckConstraint("decided_via IN ('human', 'rule', 'system')", name="ck_decisions_decided_via"),
        sa.CheckConstraint("(decided_via = 'rule') = (rule_id IS NOT NULL)", name="ck_decisions_rule_id"),
    )
    op.create_index("ix_decisions_org_decided_at", "decisions", ["org_id", "decided_at"])
    op.create_index("ix_decisions_org_target", "decisions", ["org_id", "target_type", "target_id"])
    op.create_index("uq_decisions_supersedes_id", "decisions", ["supersedes_id"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_decisions_supersedes_id", table_name="decisions")
    op.drop_index("ix_decisions_org_target", table_name="decisions")
    op.drop_index("ix_decisions_org_decided_at", table_name="decisions")
    op.drop_table("decisions")
