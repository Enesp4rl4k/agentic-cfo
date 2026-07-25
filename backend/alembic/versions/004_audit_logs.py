"""add audit_logs table for compliance

Revision ID: 004
Revises: 003
Create Date: 2024-01-04 00:00:00.000000
"""
from __future__ import annotations
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id",         sa.String(36),  nullable=True),
        sa.Column("user_email",      sa.String(255), nullable=True),
        sa.Column("user_role",       sa.String(20),  nullable=True),
        sa.Column("action",          sa.String(200), nullable=False),
        sa.Column("resource",        sa.String(500), nullable=False),
        sa.Column("request_body",    sa.JSON(),      nullable=True),
        sa.Column("response_status", sa.Integer(),   nullable=True),
        sa.Column("ip_address",      sa.String(45),  nullable=True),
        sa.Column("user_agent",      sa.String(500), nullable=True),
        sa.Column("duration_ms",     sa.Integer(),   nullable=True),
        sa.Column("reason",          sa.Text(),      nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("(datetime('now'))"),
        ),
    )
    op.create_index("ix_audit_logs_user_id",    "audit_logs", ["user_id"])
    op.create_index("ix_audit_logs_action",     "audit_logs", ["action"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_logs_created_at", table_name="audit_logs")
    op.drop_index("ix_audit_logs_action",     table_name="audit_logs")
    op.drop_index("ix_audit_logs_user_id",    table_name="audit_logs")
    op.drop_table("audit_logs")
