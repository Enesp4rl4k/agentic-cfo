"""
RAG Service (v1)

Bu sürümde:
  - Embedding + pgvector yok.
  - chunk'lar DB'ye metin olarak yazılır.
  - Retrieval: query vs chunk_text üzerinden Python TF-IDF benzerliği ile yapılır.

Amaç: agentic sistemde “kanıt (evidence) grounding” ihtiyacını kapatmak.
Sonraki iterasyonda embeddings/pgvector ile değiştirilebilir (interface kalır).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.rag_chunk import RagChunk
from app.database import session_factory

logger = logging.getLogger(__name__)


def _tokenise(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


def _tfidf_similarity(query: str, docs: list[str]) -> list[float]:
    """
    Cosine similarity on TF-IDF vectors (0..1-ish).
    Mirrors backend/app/services/agent_memory.py logic, but duplicated
    to avoid coupling and keep this module dependency-light.
    """
    if not docs:
        return []

    all_texts = [query] + docs
    all_tokens = [_tokenise(t) for t in all_texts]

    vocab = sorted({tok for toks in all_tokens for tok in toks})
    if not vocab:
        return [0.0] * len(docs)

    word_idx = {w: i for i, w in enumerate(vocab)}
    n_docs = len(all_texts)

    df = [0] * len(vocab)
    for toks in all_tokens:
        seen = set(toks)
        for tok in seen:
            if tok in word_idx:
                df[word_idx[tok]] += 1

    def _vec(toks: list[str]) -> list[float]:
        tf: dict[str, int] = {}
        for t in toks:
            tf[t] = tf.get(t, 0) + 1
        v = [0.0] * len(vocab)
        for tok, count in tf.items():
            if tok in word_idx:
                i = word_idx[tok]
                # actual formula:
                import math

                idf = math.log((n_docs + 1) / (df[i] + 1)) + 1
                v[i] = (count / max(1, len(toks))) * idf
        return v

    query_vec = _vec(all_tokens[0])
    doc_vecs = [_vec(toks) for toks in all_tokens[1:]]

    def _cosine(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        na = sum(x * x for x in a) ** 0.5
        nb = sum(x * x for x in b) ** 0.5
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)

    return [_cosine(query_vec, dv) for dv in doc_vecs]


def _chunk_text(
    text: str,
    max_chars: int = 1800,
    overlap_chars: int = 200,
) -> list[str]:
    """
    Deterministic chunking based on characters (space-normalized).
    Enough for v1 evidence retrieval; can be replaced by token-based
    chunking later.
    """
    compact = " ".join((text or "").split())
    if not compact:
        return []

    # Hard limit: avoid indexing pathological huge inputs
    compact = compact[:80_000]

    chunks: list[str] = []
    start = 0
    while start < len(compact):
        end = min(start + max_chars, len(compact))
        chunks.append(compact[start:end])
        if end >= len(compact):
            break
        start = max(0, end - overlap_chars)
    return chunks


async def index_job_text(
    db: AsyncSession,
    *,
    org_id: str,
    job_id: str,
    source_type: str,
    raw_text: str,
) -> int:
    """
    Store chunk rows for this org+job+source_type.
    Idempotent: deletes existing rows then inserts fresh chunks.
    """
    if not org_id or not job_id:
        return 0

    chunks = _chunk_text(raw_text)
    if not chunks:
        return 0

    # Idempotency: delete previous index for this job
    await db.execute(
        delete(RagChunk).where(
            RagChunk.org_id == org_id,
            RagChunk.job_id == job_id,
            RagChunk.source_type == source_type,
        )
    )

    now = datetime.now(timezone.utc)
    for i, ch in enumerate(chunks):
        db.add(
            RagChunk(
                org_id=org_id,
                job_id=job_id,
                source_type=source_type,
                chunk_index=i,
                chunk_text=ch,
                created_at=now,
            )
        )

    # Do not commit here: caller manages the transaction boundary.
    return len(chunks)


@dataclass
class EvidenceItem:
    job_id: str | None
    chunk_index: int
    score: float
    preview: str


async def retrieve_evidence(
    db: AsyncSession | None = None,
    *,
    org_id: str,
    query: str,
    job_id: str | None = None,
    job_ids: list[str] | None = None,
    top_k: int = 3,
    candidate_limit: int = 500,
    source_type: str | None = "cfo_transactions_raw",
    min_score: float = 0.06,
) -> str:
    """
    Retrieve evidence snippets and format them for LLM system prompt.
    """
    if not org_id or not query.strip():
        return ""

    async def _run(_db: AsyncSession) -> str:
        # Fetch recent candidate chunks (avoid huge candidate sets for TF-IDF)
        q = select(RagChunk.job_id, RagChunk.chunk_index, RagChunk.chunk_text).where(
            RagChunk.org_id == org_id
        )
        if source_type:
            q = q.where(RagChunk.source_type == source_type)
        if job_id:
            q = q.where(RagChunk.job_id == job_id)
        elif job_ids:
            q = q.where(RagChunk.job_id.in_(job_ids))
        q = q.order_by(RagChunk.created_at.desc()).limit(candidate_limit)
        rows = (await _db.execute(q)).all()
        if not rows:
            return ""

        job_ids: list[str | None] = [r[0] for r in rows]
        chunk_indices: list[int] = [r[1] for r in rows]
        chunk_texts: list[str] = [r[2] or "" for r in rows]

        scores = _tfidf_similarity(query, chunk_texts)
        if not scores:
            return ""

        ranked = sorted(
            zip(scores, job_ids, chunk_indices, chunk_texts),
            key=lambda x: -x[0],
        )

        evidence: list[EvidenceItem] = []
        for s, jid, idx, txt in ranked[: max(1, top_k * 3)]:
            if s < min_score:
                continue
            preview = (txt or "").strip()
            if len(preview) > 220:
                preview = preview[:220] + "..."
            evidence.append(
                EvidenceItem(
                    job_id=jid,
                    chunk_index=int(idx),
                    score=float(s),
                    preview=preview,
                )
            )
            if len(evidence) >= top_k:
                break

        if not evidence:
            return ""

        lines = ["## RAG Kanıtlar (evidence)"]
        for e in evidence:
            jid = e.job_id or "(unknown-job)"
            lines.append(
                f"- job={jid} chunk={e.chunk_index} score={e.score:.2f}: {e.preview}"
            )

        return "\n".join(lines)

    if db is not None:
        return await _run(db)

    async with session_factory()() as _db:
        return await _run(_db)

