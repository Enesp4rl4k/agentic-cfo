"""Counterparty aliases: two spellings of one supplier, confirmed by a person (plan v10 gap G23).

A new table, nothing existing changes; downgrade drops it. See app/models/counterparty_alias.py.

Revision ID: 066_counterparty_aliases
Revises: 065_invoice_key_counterparty
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "066_counterparty_aliases"
down_revision = "065_invoice_key_counterparty"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "counterparty_aliases" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "counterparty_aliases",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("alias_token", sa.String(16), nullable=False),
        sa.Column("canonical_token", sa.String(16), nullable=False),
        sa.Column("decision_id", sa.String(36), nullable=True),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("alias_name", sa.String(300), nullable=True),
        sa.Column("canonical_name", sa.String(300), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", sa.String(36), nullable=True),
        sa.Column("revoke_decision_id", sa.String(36), nullable=True),
        sa.UniqueConstraint("org_id", "alias_token", name="uq_counterparty_alias_org_token"),
    )
    op.create_index("ix_counterparty_aliases_org_id", "counterparty_aliases", ["org_id"])


def downgrade() -> None:
    if "counterparty_aliases" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("counterparty_aliases")
