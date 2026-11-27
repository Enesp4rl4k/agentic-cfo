"""Embeddings that do not match the company's current data mode or pseudonym key: count them, re-embed them.

A stored vector is tagged with how it was made (`embedding_gateway.embedding_tag`): the bare model name for raw
text, `<model>+pseud2.<key version>` for masked text. A query only compares vectors of its own tag, so after a
switch to `masked` (or a rotation of BACKEND_SECRET_KEY) the older vectors are never mixed in, and they are
not used either until they are re-embedded. That state is never silent:

* `pending(db, org_id)`: how many of the company's chunks await re-indexing (owner's privacy card,
  "N belge parçası maskeli modda yeniden dizinlenmeyi bekliyor");
* `pending_total(db)`: the same over all companies, for the operator view of `/ready`;
* `reindex_batch(db)`: the bounded re-index step the maintenance job (`worker.run_rag_backfill_maintenance`,
  cron) runs. Idempotent (a chunk whose tag already matches is never selected again), resumable (each run
  takes the next batch; every company's batch is committed on its own), rate-limited (at most `limit` chunks
  per run and `per_org` per company, one embedding call per company), and through the one embedding gateway
  (data mode, masking, fail closed and the audit row apply). `off` re-embeds nothing.

Note: production retrieval (`rag_service.retrieve_evidence`) ranks by TF-IDF today; the vectors are read by
`rag.retriever.EmbeddingRagRetriever`. Keeping their tags right is what makes enabling that retriever safe.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.rag_chunk import RagChunk
from app.platform import embedding_gateway
from app.platform.llm_egress import policy
from app.platform.llm_egress.policy import DataMode

logger = logging.getLogger(__name__)

REINDEX_LIMIT = 200
REINDEX_PER_ORG = 50


async def expected_tag(org_id: str) -> str | None:
    """The tag a vector of this company should carry now; None when nothing would be embedded."""
    if not embedding_gateway.has_embedding_support():
        return None
    mode = (await policy.effective_mode(org_id)).mode
    return None if mode == DataMode.OFF else embedding_gateway.embedding_tag(mode)


def _stale(tag: str):
    return or_(RagChunk.embedding_model.is_(None), RagChunk.embedding_model != tag)


async def pending(db: AsyncSession, org_id: str) -> dict[str, Any]:
    tag = await expected_tag(org_id)
    if tag is None:
        return {"pending": 0, "tag": None}
    count = (await db.execute(
        select(func.count()).select_from(RagChunk).where(RagChunk.org_id == org_id, _stale(tag))
    )).scalar_one()
    return {"pending": int(count), "tag": tag}


async def pending_total(db: AsyncSession, max_orgs: int = 500) -> int:
    orgs = (await db.execute(select(RagChunk.org_id).distinct().limit(max_orgs))).scalars().all()
    total = 0
    for org in orgs:
        total += (await pending(db, str(org)))["pending"]
    return total


async def reindex_batch(db: AsyncSession, *, limit: int = REINDEX_LIMIT, per_org: int = REINDEX_PER_ORG) -> int:
    """Re-embed up to `limit` stale chunks (oldest companies' backlog first served per run); returns how many."""
    from app.services.rag_service import _embed_texts

    if not embedding_gateway.has_embedding_support():
        return 0
    done = 0
    orgs = (await db.execute(select(RagChunk.org_id).distinct().order_by(RagChunk.org_id))).scalars().all()
    for org in orgs:
        if done >= limit:
            break
        tag = await expected_tag(str(org))
        if tag is None:
            continue
        rows = (await db.execute(
            select(RagChunk).where(RagChunk.org_id == org, _stale(tag))
            .order_by(RagChunk.created_at.desc()).limit(min(per_org, limit - done))
        )).scalars().all()
        if not rows:
            continue
        embedded = await _embed_texts([(c.chunk_text or "")[:8000] for c in rows], org_id=str(org), purpose="rag_reindex")
        if embedded is None or embedded.tag != tag or len(embedded.vectors) != len(rows):
            continue  # refused, failed or the mode changed meanwhile: left for the next run, nothing half-written
        for chunk, vector in zip(rows, embedded.vectors, strict=True):
            chunk.embedding, chunk.embedding_model = vector, tag
        await db.commit()
        done += len(rows)
    if done:
        logger.info("rag re-index: %d chunks re-embedded", done)
    return done
