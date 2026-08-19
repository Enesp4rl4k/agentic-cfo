"""010_sso_fields: add SSO columns to users table + IP whitelist to organizations"""
from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    # ── SEC-1: SSO fields on users ────────────────────────────────────────────
    op.add_column("users", sa.Column("sso_provider", sa.String(30), nullable=True))
    op.add_column("users", sa.Column("sso_id",       sa.String(255), nullable=True))
    op.add_column("users", sa.Column("last_login",   sa.DateTime(timezone=True), nullable=True))

    op.create_index("ix_users_sso_id", "users", ["sso_id"], unique=False)

    # ── SEC-5: IP whitelist on organizations ─────────────────────────────────
    # Stored as comma-separated CIDR ranges: "10.0.0.0/8,203.0.113.0/24"
    op.add_column(
        "organizations",
        sa.Column("ip_whitelist", sa.Text(), nullable=True, comment="Comma-separated allowed CIDRs"),
    )
    op.add_column(
        "organizations",
        sa.Column("ip_whitelist_enabled", sa.Boolean(), server_default="false", nullable=False),
    )

    # ── SEC-2: Encryption key reference ──────────────────────────────────────
    # Stores which key version was used to encrypt org data (key rotation support)
    op.add_column(
        "organizations",
        sa.Column("encryption_key_id", sa.String(36), nullable=True),
    )


def downgrade() -> None:
    op.drop_index("ix_users_sso_id", table_name="users")
    op.drop_column("users", "sso_provider")
    op.drop_column("users", "sso_id")
    op.drop_column("users", "last_login")
    op.drop_column("organizations", "ip_whitelist")
    op.drop_column("organizations", "ip_whitelist_enabled")
    op.drop_column("organizations", "encryption_key_id")
