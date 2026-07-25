"""add users table for authentication

Revision ID: 003
Revises: 002
Create Date: 2024-01-03 00:00:00.000000

Adds the users table with email/password auth, role-based access, and API key support.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(200), nullable=True),
        sa.Column("role", sa.String(20), nullable=False, server_default="analyst"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("api_key", sa.String(64), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("(datetime('now'))"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("(datetime('now'))"),
        ),
    )
    op.create_index("ix_users_email",   "users", ["email"],   unique=True)
    op.create_index("ix_users_api_key", "users", ["api_key"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_api_key", table_name="users")
    op.drop_index("ix_users_email",   table_name="users")
    op.drop_table("users")
