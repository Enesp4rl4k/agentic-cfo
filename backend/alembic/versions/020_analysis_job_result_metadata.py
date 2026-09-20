"""analysis_jobs result_metadata

Revision ID: 020
Revises: 019_rag_chunks
Create Date: 2026-08-19 00:00:00.000000
"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine.reflection import Inspector

revision: str = "020"
down_revision: Union[str, None] = "019_rag_chunks"
branch_labels: Union[str, tuple[str, ...], None] = None
depends_on: Union[str, tuple[str, ...], None] = None


def _has_column(inspector: Inspector, table_name: str, column_name: str) -> bool:
    return any(col["name"] == column_name for col in inspector.get_columns(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_column(inspector, "analysis_jobs", "result_metadata"):
        op.add_column(
            "analysis_jobs",
            sa.Column("result_metadata", sa.JSON(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_column(inspector, "analysis_jobs", "result_metadata"):
        op.drop_column("analysis_jobs", "result_metadata")

