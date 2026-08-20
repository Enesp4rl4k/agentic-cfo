"""Add international org locale fields.

Revision ID: 024_org_international_locale
Revises: 023_rag_embeddings
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "024_org_international_locale"
down_revision = "023_rag_embeddings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column("country_code", sa.String(2), nullable=False, server_default="US"),
    )
    op.add_column(
        "organizations",
        sa.Column("base_currency", sa.String(3), nullable=False, server_default="USD"),
    )
    op.add_column(
        "organizations",
        sa.Column("locale", sa.String(16), nullable=False, server_default="en-US"),
    )
    # JSON array of pack ids, e.g. ["tr"]
    op.add_column(
        "organizations",
        sa.Column(
            "regional_packs",
            sa.JSON(),
            nullable=False,
            server_default="[]",
        ),
    )


def downgrade() -> None:
    op.drop_column("organizations", "regional_packs")
    op.drop_column("organizations", "locale")
    op.drop_column("organizations", "base_currency")
    op.drop_column("organizations", "country_code")
