"""category_rules belongs to an organisation.

A category correction saved a rule with no organisation, and the upsert matched
an existing rule by vendor name alone — so one company's correction rewrote
another company's rule for the same vendor. The column is nullable: rules
written before it carry no owner and are read by nobody (no organisation's
scoped query matches NULL), which is what they already were in effect.

Revision ID: 041_category_rule_org
Revises: 040_decision_log
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "041_category_rule_org"
down_revision = "040_decision_log"
branch_labels = None
depends_on = None

_INDEX = "ix_category_rules_org_id"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "category_rules" not in inspector.get_table_names():
        return
    columns = {c["name"] for c in inspector.get_columns("category_rules")}
    if "org_id" not in columns:
        op.add_column("category_rules", sa.Column("org_id", sa.String(36), nullable=True))
    indexes = {ix["name"] for ix in sa.inspect(op.get_bind()).get_indexes("category_rules")}
    if _INDEX not in indexes:
        op.create_index(_INDEX, "category_rules", ["org_id"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "category_rules" not in inspector.get_table_names():
        return
    if _INDEX in {ix["name"] for ix in inspector.get_indexes("category_rules")}:
        op.drop_index(_INDEX, table_name="category_rules")
    if "org_id" in {c["name"] for c in inspector.get_columns("category_rules")}:
        with op.batch_alter_table("category_rules") as batch:
            batch.drop_column("org_id")
