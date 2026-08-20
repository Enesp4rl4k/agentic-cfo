"""
RAG retriever abstraction — swap TF-IDF for embeddings without changing callers.

Callers: chat.py, ceo synthesis, domain kernels (future).
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.contracts import EvidenceBundle, EvidenceCitation
from app.platform.policies import (
    RAG_DEFAULT_CANDIDATE_LIMIT,
    RAG_DEFAULT_TOP_K,
    RAG_MIN_SCORE,
)

logger = logging.getLogger(__name__)


@runtime_checkable
class RagRetriever(Protocol):
    """Protocol for evidence retrieval backends."""

    async def retrieve(
        self,
        *,
        db: AsyncSession,
        org_id: str,
        query: str,
        job_id: str | None = None,
        job_ids: list[str] | None = None,
        source_type: str | None = None,
        top_k: int = RAG_DEFAULT_TOP_K,
        candidate_limit: int = RAG_DEFAULT_CANDIDATE_LIMIT,
        min_score: float = RAG_MIN_SCORE,
    ) -> EvidenceBundle: ...


class TfidfRagRetriever:
    """
    v1 retriever — delegates scoring to rag_service TF-IDF implementation.
    Returns structured EvidenceBundle for grounding validation and UI citations.
    """

    version: str = "tfidf_v1"

    async def retrieve(
        self,
        *,
        db: AsyncSession,
        org_id: str,
        query: str,
        job_id: str | None = None,
        job_ids: list[str] | None = None,
        source_type: str | None = None,
        top_k: int = RAG_DEFAULT_TOP_K,
        candidate_limit: int = RAG_DEFAULT_CANDIDATE_LIMIT,
        min_score: float = RAG_MIN_SCORE,
    ) -> EvidenceBundle:
        from app.services import rag_service

        prompt_block = await rag_service.retrieve_evidence(
            db=db,
            org_id=org_id,
            query=query,
            job_id=job_id,
            job_ids=job_ids,
            top_k=top_k,
            candidate_limit=candidate_limit,
            source_type=source_type,
            min_score=min_score,
        )

        citations: list[EvidenceCitation] = []
        if prompt_block:
            for line in prompt_block.splitlines():
                if not line.startswith("- job="):
                    continue
                citations.append(_parse_citation_line(line, source_type or ""))

        scope = "job_scoped" if (job_id or job_ids) else "org_wide"
        if not citations and prompt_block:
            scope = "org_wide"

        return EvidenceBundle(
            query=query,
            org_id=org_id,
            citations=citations[:top_k],
            job_scope=scope,
            retriever_version=self.version,
        )


class EmbeddingRagRetriever:
    """
    v2 retriever — pgvector cosine search when embeddings are available.
    Falls back to TF-IDF if the database or runtime cannot serve vector search.
    """

    version: str = "pgvector_v2"

    def __init__(self) -> None:
        self._fallback = TfidfRagRetriever()

    async def retrieve(
        self,
        *,
        db: AsyncSession,
        org_id: str,
        query: str,
        job_id: str | None = None,
        job_ids: list[str] | None = None,
        source_type: str | None = None,
        top_k: int = RAG_DEFAULT_TOP_K,
        candidate_limit: int = RAG_DEFAULT_CANDIDATE_LIMIT,
        min_score: float = RAG_MIN_SCORE,
    ) -> EvidenceBundle:
        from app.services.rag_service import _embed_texts, _vector_literal

        if db.bind is None or db.bind.dialect.name != "postgresql":
            return await self._fallback.retrieve(
                db=db,
                org_id=org_id,
                query=query,
                job_id=job_id,
                job_ids=job_ids,
                source_type=source_type,
                top_k=top_k,
                candidate_limit=candidate_limit,
                min_score=min_score,
            )

        query_embeddings = _embed_texts([query])
        if not query_embeddings:
            return await self._fallback.retrieve(
                db=db,
                org_id=org_id,
                query=query,
                job_id=job_id,
                job_ids=job_ids,
                source_type=source_type,
                top_k=top_k,
                candidate_limit=candidate_limit,
                min_score=min_score,
            )

        vector = _vector_literal(query_embeddings[0])
        clauses = ["org_id = :org_id", "embedding IS NOT NULL"]
        params: dict[str, object] = {
            "org_id": org_id,
            "embedding": vector,
            "limit": max(1, min(top_k, candidate_limit)),
        }
        strict_scope = bool(job_id or job_ids)
        if source_type:
            clauses.append("source_type = :source_type")
            params["source_type"] = source_type
        if job_id:
            clauses.append("job_id = :job_id")
            params["job_id"] = job_id

        sql = f"""
            SELECT job_id, chunk_index, source_type, chunk_text,
                   1 - (embedding <=> CAST(:embedding AS vector)) AS score
            FROM rag_chunks
            WHERE {' AND '.join(clauses)}
            ORDER BY embedding <=> CAST(:embedding AS vector)
            LIMIT :limit
        """
        try:
            rows = (await db.execute(text(sql), params)).all()
            scope = "job_scoped" if strict_scope else "org_wide"
            if not rows and strict_scope:
                fallback_sql = """
                    SELECT job_id, chunk_index, source_type, chunk_text,
                           1 - (embedding <=> CAST(:embedding AS vector)) AS score
                    FROM rag_chunks
                    WHERE org_id = :org_id AND embedding IS NOT NULL
                    ORDER BY embedding <=> CAST(:embedding AS vector)
                    LIMIT :limit
                """
                rows = (await db.execute(text(fallback_sql), params)).all()
                scope = "org_wide"
        except Exception as exc:
            logger.warning("pgvector retrieval failed, falling back to TF-IDF: %s", exc)
            return await self._fallback.retrieve(
                db=db,
                org_id=org_id,
                query=query,
                job_id=job_id,
                job_ids=job_ids,
                source_type=source_type,
                top_k=top_k,
                candidate_limit=candidate_limit,
                min_score=min_score,
            )

        citations: list[EvidenceCitation] = []
        for row in rows:
            score = float(row[4] or 0.0)
            if score < min_score:
                continue
            raw_preview = (row[3] or "").strip()
            preview = raw_preview[:220] + ("..." if len(raw_preview) > 220 else "")
            citations.append(
                EvidenceCitation(
                    job_id=row[0],
                    chunk_index=int(row[1]),
                    source_type=str(row[2] or source_type or ""),
                    score=score,
                    preview=preview,
                )
            )

        if not citations:
            return await self._fallback.retrieve(
                db=db,
                org_id=org_id,
                query=query,
                job_id=job_id,
                job_ids=job_ids,
                source_type=source_type,
                top_k=top_k,
                candidate_limit=candidate_limit,
                min_score=min_score,
            )

        return EvidenceBundle(
            query=query,
            org_id=org_id,
            citations=citations[:top_k],
            job_scope=scope,
            retriever_version=self.version,
        )


def _parse_citation_line(line: str, default_source: str) -> EvidenceCitation:
    """Parse rag_service prompt line into EvidenceCitation (best-effort)."""
    try:
        body = line[2:].strip()
        meta, preview = body.split(": ", 1)
        parts = dict(p.split("=", 1) for p in meta.split() if "=" in p)
        return EvidenceCitation(
            job_id=parts.get("job"),
            chunk_index=int(parts.get("chunk", 0)),
            source_type=default_source,
            score=float(parts.get("score", 0)),
            preview=preview,
        )
    except Exception:
        return EvidenceCitation(
            job_id=None,
            chunk_index=0,
            source_type=default_source,
            score=0.0,
            preview=line,
        )


_default_retriever: RagRetriever | None = None


def get_rag_retriever() -> RagRetriever:
    global _default_retriever
    if _default_retriever is None:
        _default_retriever = EmbeddingRagRetriever()
    return _default_retriever
