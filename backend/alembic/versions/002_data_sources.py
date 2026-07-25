"""add data_sources table for multi-domain file uploads

Revision ID: 002
Revises: 001
Create Date: 2024-01-02 00:00:00.000000

Adds the data_sources table that stores domain-specific uploaded files
(CTO billing, CHRO headcount, CMO campaigns, COO SLAs) tied to an AnalysisJob.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "data_sources",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "job_id",
            sa.String(36),
            sa.ForeignKey("analysis_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("domain", sa.String(20), nullable=False),
        # cfo | cto | chro | cmo | coo
        sa.Column("source_type", sa.String(30), nullable=False),
        # cloud_billing | headcount | campaign | ...
        sa.Column("filename", sa.String(500), nullable=False),
        sa.Column("file_path", sa.String(1000), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=True),
        sa.Column("label", sa.String(200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("(datetime('now'))"),
        ),
    )
    op.create_index("ix_data_sources_job_id", "data_sources", ["job_id"])
    op.create_index("ix_data_sources_domain", "data_sources", ["domain"])


def downgrade() -> None:
    op.drop_index("ix_data_sources_domain", table_name="data_sources")
    op.drop_index("ix_data_sources_job_id", table_name="data_sources")
    op.drop_table("data_sources")
