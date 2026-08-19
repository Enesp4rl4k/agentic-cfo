"""smmm_portal: SMMM portal tablolari

Revision ID: 009
Revises: 008
Create Date: 2026-08-01
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "smmm_muhasebeci",
        sa.Column("id",           sa.String(36),  nullable=False),
        sa.Column("user_id",      sa.String(36),  nullable=False),
        sa.Column("unvan",        sa.String(200), nullable=True),
        sa.Column("vergi_no",     sa.String(20),  nullable=True),
        sa.Column("oda_no",       sa.String(50),  nullable=True),
        sa.Column("firma_adi",    sa.String(200), nullable=True),
        sa.Column("il",           sa.String(50),  nullable=True),
        sa.Column("telefon",      sa.String(30),  nullable=True),
        sa.Column("plan",         sa.String(20),  nullable=False, server_default="free"),
        sa.Column("max_clients",  sa.Integer,     nullable=False, server_default="5"),
        sa.Column("is_active",    sa.Boolean,     nullable=False, server_default="1"),
        sa.Column("created_at",   sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at",   sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_table(
        "smmm_musteri_kayit",
        sa.Column("id",               sa.String(36),  nullable=False),
        sa.Column("muhasebeci_id",    sa.String(36),  nullable=False),
        sa.Column("firma_adi",        sa.String(200), nullable=False),
        sa.Column("vergi_no",         sa.String(20),  nullable=True),
        sa.Column("sektor",           sa.String(50),  nullable=True),
        sa.Column("buyukluk",         sa.String(20),  nullable=True),
        sa.Column("il",               sa.String(50),  nullable=True),
        sa.Column("client_org_id",    sa.String(36),  nullable=True),
        sa.Column("last_analysis_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_job_id",      sa.String(36),  nullable=True),
        sa.Column("health_score",     sa.Float,       nullable=True),
        sa.Column("health_label",     sa.String(20),  nullable=True),
        sa.Column("is_active",        sa.Boolean,     nullable=False, server_default="1"),
        sa.Column("notlar",           sa.Text,        nullable=True),
        sa.Column("created_at",       sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at",       sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["muhasebeci_id"], ["smmm_muhasebeci.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_smmm_musteri_muhasebeci", "smmm_musteri_kayit", ["muhasebeci_id"])
    op.create_table(
        "proactive_alerts",
        sa.Column("alert_id",   sa.String(36),  nullable=False),
        sa.Column("org_id",     sa.String(36),  nullable=False),
        sa.Column("trigger",    sa.String(50),  nullable=False),
        sa.Column("severity",   sa.String(20),  nullable=False),
        sa.Column("title",      sa.String(300), nullable=False),
        sa.Column("body",       sa.Text,        nullable=True),
        sa.Column("metadata",   sa.Text,        nullable=True),
        sa.Column("channels",   sa.Text,        nullable=True),
        sa.Column("created_at", sa.Float,       nullable=False),
        sa.Column("dispatched", sa.Boolean,     nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("alert_id"),
    )
    op.create_index("ix_proactive_alerts_org", "proactive_alerts", ["org_id"])
    op.create_index("ix_proactive_alerts_severity", "proactive_alerts", ["severity"])


def downgrade() -> None:
    op.drop_table("smmm_musteri_kayit")
    op.drop_table("smmm_muhasebeci")
    op.drop_table("proactive_alerts")
