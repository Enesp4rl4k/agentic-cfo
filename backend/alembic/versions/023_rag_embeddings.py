"""
023 — rag chunk embeddings: pgvector-ready storage with safe SQLite fallback

Adds nullable embedding metadata to rag_chunks.
- PostgreSQL: creates pgvector extension and vector(1536) column + ivfflat index
- SQLite/other: stores embeddings as JSON text for dev/test compatibility

Revision ID: 023_rag_embeddings
Revises:     022_sync_runs_and_canonical_idempotency
Create Date: 2026-08-19
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "023_rag_embeddings"
down_revision = "022_sync_runs_and_canonical_idempotency"
branch_labels = None
depends_on = None


def _is_postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {c["name"] for c in inspector.get_columns("rag_chunks")}

    if "embedding_model" not in columns:
        op.add_column("rag_chunks", sa.Column("embedding_model", sa.String(100), nullable=True))

    if "embedding" not in columns:
        if _is_postgresql():
            op.execute("CREATE EXTENSION IF NOT EXISTS vector")
            op.execute("ALTER TABLE rag_chunks ADD COLUMN embedding vector(1536)")
            op.execute(
                """
                CREATE INDEX IF NOT EXISTS ix_rag_chunks_embedding_ivfflat
                ON rag_chunks
                USING ivfflat (embedding vector_cosine_ops)
                WITH (lists = 100)
                """
            )
        else:
            op.add_column("rag_chunks", sa.Column("embedding", sa.JSON(), nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {c["name"] for c in inspector.get_columns("rag_chunks")}

    if _is_postgresql():
        op.execute("DROP INDEX IF EXISTS ix_rag_chunks_embedding_ivfflat")

    if "embedding" in columns:
        op.drop_column("rag_chunks", "embedding")
    if "embedding_model" in columns:
        op.drop_column("rag_chunks", "embedding_model")
