"""E-mail verification: `users.email_verified_at` and the verification tokens.

Every account that exists when this runs is marked verified (its `created_at`, else now): pre-pilot
data, and nobody may be locked out by a rule they were never asked to meet. Accounts registered after
this are unverified until their address is proved.

Downgrade drops the table and the column.

Revision ID: 072_email_verification
Revises: 071_pwreset_outbox_classes
"""
from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision = "072_email_verification"
down_revision = "071_pwreset_outbox_classes"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    tables = _tables()
    if "users" in tables:
        have = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("users")}
        if "email_verified_at" not in have:
            op.add_column("users", sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True))
        users = sa.table(
            "users", sa.column("email_verified_at", sa.DateTime(timezone=True)),
            sa.column("created_at", sa.DateTime(timezone=True)),
        )
        op.get_bind().execute(
            sa.update(users).where(users.c.email_verified_at.is_(None)).values(
                email_verified_at=sa.func.coalesce(users.c.created_at, datetime.now(UTC))
            )
        )
    if "email_verification_tokens" not in tables:
        op.create_table(
            "email_verification_tokens",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("token_hash", sa.String(64), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index(
            "ix_email_verification_tokens_token_hash", "email_verification_tokens", ["token_hash"], unique=True
        )
        op.create_index(
            "ix_email_verification_tokens_user_open", "email_verification_tokens", ["user_id", "used_at"]
        )


def downgrade() -> None:
    tables = _tables()
    if "email_verification_tokens" in tables:
        op.drop_index("ix_email_verification_tokens_user_open", table_name="email_verification_tokens")
        op.drop_index("ix_email_verification_tokens_token_hash", table_name="email_verification_tokens")
        op.drop_table("email_verification_tokens")
    if "users" in tables:
        have = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("users")}
        if "email_verified_at" in have:
            op.drop_column("users", "email_verified_at")
