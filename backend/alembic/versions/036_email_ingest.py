"""E-postayla veri: an organisation's data mail address, and the mail it received.

The ingest address used to be derived from the organisation id and stored
nowhere, so it could not be replaced, and nothing received mail sent to it.

Revision ID: 036_email_ingest
Revises: 035_transaction_tax_amounts
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "036_email_ingest"
down_revision = "035_transaction_tax_amounts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "email_ingest_addresses" not in tables:
        op.create_table(
            "email_ingest_addresses",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("kod", sa.String(32), nullable=False),
            sa.Column("created_by", sa.String(36), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_email_ingest_addresses_org_id", "email_ingest_addresses", ["org_id"])
        op.create_index("ix_email_ingest_addresses_kod", "email_ingest_addresses", ["kod"], unique=True)
    if "email_ingest_messages" not in tables:
        op.create_table(
            "email_ingest_messages",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), nullable=False),
            sa.Column("address_id", sa.String(36), nullable=False),
            sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("sender", sa.String(500), nullable=False),
            sa.Column("subject", sa.String(500), nullable=False),
            sa.Column("message_id", sa.String(500), nullable=True),
            sa.Column("sonuclar", sa.JSON(), nullable=False),
        )
        op.create_index("ix_email_ingest_messages_org_id", "email_ingest_messages", ["org_id"])


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "email_ingest_messages" in tables:
        op.drop_index("ix_email_ingest_messages_org_id", table_name="email_ingest_messages")
        op.drop_table("email_ingest_messages")
    if "email_ingest_addresses" in tables:
        op.drop_index("ix_email_ingest_addresses_kod", table_name="email_ingest_addresses")
        op.drop_index("ix_email_ingest_addresses_org_id", table_name="email_ingest_addresses")
        op.drop_table("email_ingest_addresses")
