"""
RAG retriever abstraction — swap TF-IDF for embeddings without changing callers.

Callers: chat.py, ceo synthesis, domain kernels (future).
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Protocol, runtime_checkable

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
            scope = "org_wide"  # fallback was used inside rag_service

        return EvidenceBundle(
            query=query,
            org_id=org_id,
            citations=citations[:top_k],
            job_scope=scope,
            retriever_version=self.version,
        )


def _parse_citation_line(line: str, default_source: str) -> EvidenceCitation:
    """Parse rag_service prompt line into EvidenceCitation (best-effort)."""
    # Format: - job={jid} chunk={idx} score={s}: {preview}
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


_default_retriever: TfidfRagRetriever | None = None


def get_rag_retriever() -> RagRetriever:
    global _default_retriever
    if _default_retriever is None:
        _default_retriever = TfidfRagRetriever()
    return _default_retriever
