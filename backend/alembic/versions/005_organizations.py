"""organizations: add organizations, org_invites tables; add org_id to users and analysis_jobs; add user_id to analysis_jobs

Revision ID: 005
Revises: 004
Create Date: 2026-07-25
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. organizations table ────────────────────────────────────────────────
    op.create_table(
        "organizations",
        sa.Column("id",                 sa.String(36),  nullable=False),
        sa.Column("name",               sa.String(200), nullable=False),
        sa.Column("slug",               sa.String(100), nullable=False),
        sa.Column("logo_url",           sa.String(500), nullable=True),
        sa.Column("description",        sa.Text(),      nullable=True),
        sa.Column("plan",               sa.String(20),  nullable=False, server_default="free"),
        sa.Column("max_members",        sa.Integer(),   nullable=False, server_default="5"),
        sa.Column("max_jobs_per_month", sa.Integer(),   nullable=False, server_default="20"),
        sa.Column("is_active",          sa.Boolean(),   nullable=False, server_default="1"),
        sa.Column("created_at",         sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at",         sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_organizations_slug"),
    )
    op.create_index("ix_organizations_slug", "organizations", ["slug"])

    # ── 2. org_invites table ──────────────────────────────────────────────────
    op.create_table(
        "org_invites",
        sa.Column("id",         sa.String(36),  nullable=False),
        sa.Column("org_id",     sa.String(36),  nullable=False),
        sa.Column("email",      sa.String(255), nullable=False),
        sa.Column("role",       sa.String(20),  nullable=False, server_default="analyst"),
        sa.Column("token",      sa.String(64),  nullable=False),
        sa.Column("accepted",   sa.Boolean(),   nullable=False, server_default="0"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("token", name="uq_org_invites_token"),
    )
    op.create_index("ix_org_invites_org_id", "org_invites", ["org_id"])
    op.create_index("ix_org_invites_token",  "org_invites", ["token"])

    # ── 3. Add org_id to users ────────────────────────────────────────────────
    op.add_column(
        "users",
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_users_org_id", "users", ["org_id"])

    # ── 4. Add user_id + org_id to analysis_jobs ─────────────────────────────
    op.add_column(
        "analysis_jobs",
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )
    op.add_column(
        "analysis_jobs",
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_analysis_jobs_user_id", "analysis_jobs", ["user_id"])
    op.create_index("ix_analysis_jobs_org_id",  "analysis_jobs", ["org_id"])


def downgrade() -> None:
    op.drop_index("ix_analysis_jobs_org_id",  table_name="analysis_jobs")
    op.drop_index("ix_analysis_jobs_user_id", table_name="analysis_jobs")
    op.drop_column("analysis_jobs", "org_id")
    op.drop_column("analysis_jobs", "user_id")

    op.drop_index("ix_users_org_id", table_name="users")
    op.drop_column("users", "org_id")

    op.drop_index("ix_org_invites_token",  table_name="org_invites")
    op.drop_index("ix_org_invites_org_id", table_name="org_invites")
    op.drop_table("org_invites")

    op.drop_index("ix_organizations_slug", table_name="organizations")
    op.drop_table("organizations")
