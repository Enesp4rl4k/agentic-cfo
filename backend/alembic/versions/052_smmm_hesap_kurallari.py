"""Accounts an organisation's accountant has corrected recurring descriptions to.

Plan SMMM agent: what the accountant corrects, the agent remembers. One new
table; nothing changes for an organisation that never corrects an account.

Revision ID: 052_smmm_hesap_kurallari
Revises: 051_org_vkn
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "052_smmm_hesap_kurallari"
down_revision = "051_org_vkn"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "smmm_hesap_kurallari" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "smmm_hesap_kurallari",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("anahtar", sa.String(300), nullable=False),
        sa.Column("hesap_kodu", sa.String(20), nullable=False),
        sa.Column("hesap_adi", sa.String(200), nullable=True),
        sa.Column("onay_sayisi", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("org_id", "anahtar", "hesap_kodu", name="uq_smmm_hesap_kurali"),
    )
    op.create_index("ix_smmm_hesap_kurallari_org_id", "smmm_hesap_kurallari", ["org_id"])
    op.create_index("ix_smmm_hesap_kurallari_anahtar", "smmm_hesap_kurallari", ["anahtar"])


def downgrade() -> None:
    if "smmm_hesap_kurallari" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("smmm_hesap_kurallari")
