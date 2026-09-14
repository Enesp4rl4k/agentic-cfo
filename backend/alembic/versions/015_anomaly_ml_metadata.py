"""
015 — anomaly_ml_metadata: anomaly tablosuna ML detector alanları

Adds detector_type, confidence_lower, confidence_upper columns
to the anomalies table for Sprint L1 ML anomaly detection results.

Revision ID: 015_anomaly_ml_metadata
Revises:     014_usage_events
Create Date: 2026-08-04
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision      = "015_anomaly_ml_metadata"
down_revision = "014_usage_events"
branch_labels = None
depends_on    = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables    = inspector.get_table_names()

    if "anomalies" not in tables:
        return  # Nothing to migrate

    existing_cols = {c["name"] for c in inspector.get_columns("anomalies")}

    # detector_type: "isolation_forest" | "dbscan" | "rule_based" | "ensemble"
    if "detector_type" not in existing_cols:
        op.add_column(
            "anomalies",
            sa.Column("detector_type", sa.String(50), nullable=True, server_default="rule_based"),
        )

    # confidence_lower / confidence_upper: bootstrap CI bounds (0.0–1.0)
    if "confidence_lower" not in existing_cols:
        op.add_column(
            "anomalies",
            sa.Column("confidence_lower", sa.Float(), nullable=True),
        )

    if "confidence_upper" not in existing_cols:
        op.add_column(
            "anomalies",
            sa.Column("confidence_upper", sa.Float(), nullable=True),
        )

    # ml_score: normalized anomaly score (0.0 = normal, 1.0 = most anomalous)
    if "ml_score" not in existing_cols:
        op.add_column(
            "anomalies",
            sa.Column("ml_score", sa.Float(), nullable=True),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables    = inspector.get_table_names()

    if "anomalies" not in tables:
        return

    existing_cols = {c["name"] for c in inspector.get_columns("anomalies")}

    for col in ("ml_score", "confidence_upper", "confidence_lower", "detector_type"):
        if col in existing_cols:
            op.drop_column("anomalies", col)
