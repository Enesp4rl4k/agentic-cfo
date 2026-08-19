"""
019 — rag_chunks: chunk storage + TF-IDF retrieval v1

Creates DB-backed storage for RAG evidence chunks.
For v1:
  - Indexing is done from CFO pipeline output (worker) using transaction raw_text.
  - Retrieval uses TF-IDF similarity computed in Python (no pgvector dependency yet).

Revision ID: 019_rag_chunks
Revises:     018_alert_tables
Create Date: 2026-08-19
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "019_rag_chunks"
down_revision = "018_alert_tables"
branch_labels = None
depends_on = None


def _is_postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = inspector.get_table_names()

    if "rag_chunks" not in tables:
        op.create_table(
            "rag_chunks",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), nullable=False),
            sa.Column("job_id", sa.String(36), nullable=True),
            sa.Column("source_type", sa.String(50), nullable=False),
            sa.Column("chunk_index", sa.Integer(), nullable=False),
            sa.Column("chunk_text", sa.Text(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.UniqueConstraint(
                "org_id", "job_id", "source_type", "chunk_index", name="uq_rag_chunks_job"
            ),
        )

        op.create_index("ix_rag_chunks_org_id", "rag_chunks", ["org_id"])
        op.create_index("ix_rag_chunks_job_id", "rag_chunks", ["job_id"])
        op.create_index(
            "ix_rag_chunks_source_type_created_at",
            "rag_chunks",
            ["source_type", "created_at"],
        )

    # Best-effort: add FK constraints only when they make sense (Postgres/SQLite differences).
    # We keep this migration minimal to avoid FK ordering issues in fresh DBs.
    # If you want strict FK enforcement, add them in a follow-up migration.


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = inspector.get_table_names()
    if "rag_chunks" in tables:
        op.drop_table("rag_chunks")

