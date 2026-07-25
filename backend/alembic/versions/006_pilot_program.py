"""pilot_program: add pilot_invites and user_feedback tables

Revision ID: 006
Revises: 005
Create Date: 2026-07-25
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── pilot_invites ──────────────────────────────────────────────────────────
    op.create_table(
        "pilot_invites",
        sa.Column("id",               sa.String(36),  nullable=False),
        sa.Column("code",             sa.String(32),  nullable=False),
        sa.Column("email",            sa.String(255), nullable=True),
        sa.Column("note",             sa.String(500), nullable=True),
        sa.Column("used",             sa.Boolean(),   nullable=False, server_default="0"),
        sa.Column("used_by_user_id",  sa.String(36),  nullable=True),
        sa.Column("used_at",          sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at",       sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at",       sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_pilot_invites_code"),
    )
    op.create_index("ix_pilot_invites_code", "pilot_invites", ["code"])

    # ── user_feedback ──────────────────────────────────────────────────────────
    op.create_table(
        "user_feedback",
        sa.Column("id",               sa.String(36),  nullable=False),
        sa.Column("user_id",          sa.String(36),  nullable=True),
        sa.Column("job_id",           sa.String(36),  nullable=True),
        sa.Column("org_id",           sa.String(36),  nullable=True),
        sa.Column("nps_score",        sa.Integer(),   nullable=True),
        sa.Column("analysis_rating",  sa.Integer(),   nullable=True),
        sa.Column("accuracy_rating",  sa.Integer(),   nullable=True),
        sa.Column("usefulness_rating", sa.Integer(),  nullable=True),
        sa.Column("speed_rating",     sa.Integer(),   nullable=True),
        sa.Column("comment",          sa.Text(),      nullable=True),
        sa.Column("biggest_benefit",  sa.Text(),      nullable=True),
        sa.Column("biggest_gap",      sa.Text(),      nullable=True),
        sa.Column("page_context",     sa.String(100), nullable=True),
        sa.Column("dismissed",        sa.Boolean(),   nullable=False, server_default="0"),
        sa.Column("created_at",       sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["job_id"],  ["analysis_jobs.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_user_feedback_user_id", "user_feedback", ["user_id"])
    op.create_index("ix_user_feedback_job_id",  "user_feedback", ["job_id"])
    op.create_index("ix_user_feedback_org_id",  "user_feedback", ["org_id"])


def downgrade() -> None:
    op.drop_index("ix_user_feedback_org_id",  table_name="user_feedback")
    op.drop_index("ix_user_feedback_job_id",  table_name="user_feedback")
    op.drop_index("ix_user_feedback_user_id", table_name="user_feedback")
    op.drop_table("user_feedback")

    op.drop_index("ix_pilot_invites_code", table_name="pilot_invites")
    op.drop_table("pilot_invites")
