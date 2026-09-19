"""İlişkili taraf sicili: related_parties.

Revision ID: 032_related_parties
Revises: 031_institutionalization
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "032_related_parties"
down_revision = "031_institutionalization"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "related_parties" in inspector.get_table_names():
        return

    op.create_table(
        "related_parties",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("normalized_name", sa.String(length=300), nullable=False),
        sa.Column("relationship_type", sa.String(length=30), nullable=False,
                  server_default="diger"),
        sa.Column("tax_id", sa.String(length=20), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_related_parties_org_id", "related_parties", ["org_id"])
    op.create_index("ix_related_parties_tax_id", "related_parties", ["tax_id"])
    op.create_index(
        "ix_related_parties_org_active", "related_parties", ["org_id", "active"]
    )
    op.create_index(
        "ix_related_parties_org_norm", "related_parties", ["org_id", "normalized_name"]
    )


def downgrade() -> None:
    op.drop_index("ix_related_parties_org_norm", table_name="related_parties")
    op.drop_index("ix_related_parties_org_active", table_name="related_parties")
    op.drop_index("ix_related_parties_tax_id", table_name="related_parties")
    op.drop_index("ix_related_parties_org_id", table_name="related_parties")
    op.drop_table("related_parties")
