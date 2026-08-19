"""
017 — compliance_extended: SOX certifications + GDPR breach notifications

Creates tables for Sprint L3 Compliance Extended:
  - compliance_certifications: SOX 302/404 CEO/CFO sertifikaları
  - breach_notifications: GDPR Article 33 ihlal bildirimleri + 72h deadline

Revision ID: 017_compliance_extended
Revises:     016_agent_conflicts
Create Date: 2026-08-04
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision      = "017_compliance_extended"
down_revision = "016_agent_conflicts"
branch_labels = None
depends_on    = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables    = inspector.get_table_names()

    # ── compliance_certifications ─────────────────────────────────────────────
    if "compliance_certifications" not in tables:
        op.create_table(
            "compliance_certifications",
            sa.Column("id",              sa.String(32),  primary_key=True),
            sa.Column("org_id",          sa.String(36),  nullable=False, index=True),
            sa.Column("framework",       sa.String(20),  nullable=False),  # 'sox_302', 'sox_404', 'gdpr_dpa'
            sa.Column("period",          sa.String(20),  nullable=False),  # '2024-Q2'
            sa.Column("certifier_name",  sa.String(200), nullable=False),
            sa.Column("certifier_role",  sa.String(100), nullable=False),
            sa.Column("statements",      sa.Text(),      nullable=True),   # JSON array of booleans
            sa.Column("signature_hash",  sa.String(64),  nullable=True),   # SHA-256
            sa.Column("certified_at",    sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        op.create_index(
            "ix_compliance_certifications_org",
            "compliance_certifications",
            ["org_id", "framework"],
        )

    # ── breach_notifications ──────────────────────────────────────────────────
    if "breach_notifications" not in tables:
        op.create_table(
            "breach_notifications",
            sa.Column("id",             sa.String(32),  primary_key=True),
            sa.Column("org_id",         sa.String(36),  nullable=False, index=True),
            sa.Column("description",    sa.Text(),      nullable=False),
            sa.Column("severity",       sa.String(20),  nullable=False, server_default="medium"),
            sa.Column("affected_users", sa.Integer(),   nullable=False, server_default="0"),
            sa.Column("discovered_at",  sa.DateTime(timezone=True), nullable=False),
            sa.Column("deadline_72h",   sa.DateTime(timezone=True), nullable=False),
            sa.Column("notified_at",    sa.DateTime(timezone=True), nullable=True),
            sa.Column("status",         sa.String(20),  nullable=False, server_default="pending"),
            sa.Column("created_at",     sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        op.create_index(
            "ix_breach_notifications_org_status",
            "breach_notifications",
            ["org_id", "status"],
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables    = inspector.get_table_names()

    if "breach_notifications" in tables:
        op.drop_index("ix_breach_notifications_org_status", table_name="breach_notifications")
        op.drop_table("breach_notifications")

    if "compliance_certifications" in tables:
        op.drop_index("ix_compliance_certifications_org", table_name="compliance_certifications")
        op.drop_table("compliance_certifications")
