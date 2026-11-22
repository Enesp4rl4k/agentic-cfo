"""Password reset, the outbox's delivery classes, and invitation tokens stored hashed.

- `users.token_version` / `password_changed_at`: a reset raises the version; a token carries the
  version it was issued under, so every earlier session ends.
- `password_reset_tokens`: single-use reset tokens, stored as SHA-256 digests with an expiry.
- `outbox_messages.delivery_class` / `kind` / `transport`: released vs immediate messages, the
  immediate template kind, and how a message was delivered (smtp, http, or a recorded no-op).
- `org_invites.token` now holds the SHA-256 digest of the e-mailed token. Existing plain tokens
  are hashed in place, so invitation links already sent keep working (the page presents the
  plain token; the lookup hashes it). The column keeps its name.

Downgrade removes what was added. It cannot restore plain invitation tokens (they were never
kept), so it expires the invitations that are still open; they must be sent again.

Revision ID: 071_pwreset_outbox_classes
Revises: 070_direction_mappings
"""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision = "071_pwreset_outbox_classes"
down_revision = "070_direction_mappings"
branch_labels = None
depends_on = None


def _digest(raw: str) -> str:
    # Same as app.services.secret_tokens.hash_token (a test keeps them equal); copied so a
    # migration never changes meaning when app code does.
    return hashlib.sha256(raw.strip().encode("utf-8")).hexdigest()


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    tables = _tables()
    if "users" in tables:
        have = _columns("users")
        if "token_version" not in have:
            op.add_column("users", sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"))
        if "password_changed_at" not in have:
            op.add_column("users", sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True))

    if "password_reset_tokens" not in tables:
        op.create_table(
            "password_reset_tokens",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("token_hash", sa.String(64), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_password_reset_tokens_token_hash", "password_reset_tokens", ["token_hash"], unique=True)
        op.create_index("ix_password_reset_tokens_user_open", "password_reset_tokens", ["user_id", "used_at"])

    if "outbox_messages" in tables:
        have = _columns("outbox_messages")
        if "delivery_class" not in have:
            op.add_column(
                "outbox_messages",
                sa.Column("delivery_class", sa.String(20), nullable=False, server_default="released"),
            )
        if "kind" not in have:
            op.add_column("outbox_messages", sa.Column("kind", sa.String(50), nullable=True))
        if "transport" not in have:
            op.add_column("outbox_messages", sa.Column("transport", sa.String(20), nullable=True))

    if "org_invites" in tables:
        bind = op.get_bind()
        invites = sa.table("org_invites", sa.column("id"), sa.column("token"))
        for invite_id, token in bind.execute(sa.select(invites.c.id, invites.c.token)).all():
            bind.execute(sa.update(invites).where(invites.c.id == invite_id).values(token=_digest(token)))


def downgrade() -> None:
    tables = _tables()
    if "org_invites" in tables:
        bind = op.get_bind()
        open_invites = sa.table(
            "org_invites", sa.column("accepted", sa.Boolean), sa.column("expires_at", sa.DateTime(timezone=True))
        )
        bind.execute(
            sa.update(open_invites).where(open_invites.c.accepted.is_(False)).values(expires_at=datetime.now(UTC))
        )
    if "outbox_messages" in tables:
        have = _columns("outbox_messages")
        for name in ("transport", "kind", "delivery_class"):
            if name in have:
                op.drop_column("outbox_messages", name)
    if "password_reset_tokens" in tables:
        op.drop_index("ix_password_reset_tokens_user_open", table_name="password_reset_tokens")
        op.drop_index("ix_password_reset_tokens_token_hash", table_name="password_reset_tokens")
        op.drop_table("password_reset_tokens")
    if "users" in tables:
        have = _columns("users")
        for name in ("password_changed_at", "token_version"):
            if name in have:
                op.drop_column("users", name)
