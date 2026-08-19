"""Add stripe subscription fields to organizations

Revision ID: 011_stripe_billing
Revises: 010_sso_fields
Create Date: 2026-08-01
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "011_stripe_billing"
down_revision = "010_sso_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("organizations", sa.Column(
        "subscription_plan", sa.String(30), nullable=False, server_default="free"
    ))
    op.add_column("organizations", sa.Column(
        "subscription_status", sa.String(30), nullable=False, server_default="inactive"
    ))
    op.add_column("organizations", sa.Column(
        "stripe_customer_id", sa.String(100), nullable=True
    ))
    op.add_column("organizations", sa.Column(
        "stripe_subscription_id", sa.String(100), nullable=True
    ))
    op.add_column("organizations", sa.Column(
        "subscription_period_end", sa.DateTime(timezone=True), nullable=True
    ))

    op.create_index(
        "ix_organizations_stripe_customer_id",
        "organizations",
        ["stripe_customer_id"],
        unique=False,
    )
    op.create_index(
        "ix_organizations_stripe_subscription_id",
        "organizations",
        ["stripe_subscription_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_organizations_stripe_subscription_id", table_name="organizations")
    op.drop_index("ix_organizations_stripe_customer_id", table_name="organizations")
    op.drop_column("organizations", "subscription_period_end")
    op.drop_column("organizations", "stripe_subscription_id")
    op.drop_column("organizations", "stripe_customer_id")
    op.drop_column("organizations", "subscription_status")
    op.drop_column("organizations", "subscription_plan")
