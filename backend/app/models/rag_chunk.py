import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

try:
    from pgvector.sqlalchemy import Vector
except Exception:  # pragma: no cover - dependency/import edge
    Vector = None

if TYPE_CHECKING:
    from app.models.organization import Organization

    # job_id FK is best-effort for now (CFO pipeline uses analysis_jobs.id)
    from app.models.analysis_job import AnalysisJob


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RagChunk(Base):
    """
    Minimal “document RAG” storage.

    For v1 we index CFO pipeline output raw_text into chunk rows, then use
    TF-IDF similarity in Python (no extra embedding dependencies).
    """

    __tablename__ = "rag_chunks"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Source of this chunk. For now we treat CFO job as the main ingestion driver.
    job_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("analysis_jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )

    source_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)  # e.g. "cfo_transactions_raw"

    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    if Vector is not None:
        embedding: Mapped[list[float] | None] = mapped_column(
            Vector(1536).with_variant(JSON(), "sqlite"),
            nullable=True,
        )
    else:
        embedding: Mapped[list[float] | None] = mapped_column(JSON(), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("org_id", "job_id", "source_type", "chunk_index", name="uq_rag_chunks_job"),
    )

