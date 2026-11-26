"""Embedding Gateway — the single egress point for every embedding call (sibling of the Model Gateway).

Nothing else may construct an embeddings client. It applies the same data mode as chat:

  off     no call; the caller falls back to TF-IDF (the product's own retrieval, local)
  masked  the text is pseudonymised with STABLE per-organisation tokens before it leaves, for indexing
          AND for the query, so a name in a chunk and the same name in a question embed alike. The stored
          row is tagged `<model>+pseud1`; a query only searches rows of its own tag, so vectors computed
          on raw text (before masking existed) are never compared with vectors of masked text.
  raw     today's behaviour, byte for byte, tagged with the bare model name.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from app.config import get_settings
from app.platform.llm_egress import audit
from app.platform.llm_egress.policy import DataMode, PolicyOff
from app.platform.llm_egress.session import STABLE_TAG, CallTally, open_session

logger = logging.getLogger(__name__)

_PLACEHOLDER_PREFIX = "llm-placeholder-"


@dataclass(frozen=True)
class Embedded:
    vectors: list[list[float]]
    tag: str  # what to store in rag_chunks.embedding_model, and to filter by when querying


def embedding_tag(mode: DataMode) -> str:
    model = get_settings().rag_embedding_model
    return model + STABLE_TAG if mode == DataMode.MASKED else model


def _has_embedding_support() -> bool:
    settings = get_settings()
    key = (settings.openai_api_key or "").strip()
    return settings.rag_embedding_enabled and bool(key) and not key.startswith(_PLACEHOLDER_PREFIX)


def has_embedding_support() -> bool:
    return _has_embedding_support()


def _client_embed(texts: list[str]) -> list[list[float]]:
    from langchain_openai import OpenAIEmbeddings

    settings = get_settings()
    client = OpenAIEmbeddings(
        model=settings.rag_embedding_model,
        api_key=settings.openai_api_key,  # type: ignore[arg-type]  # langchain coerces str to SecretStr
        base_url=settings.llm_base_url or None,
        dimensions=settings.rag_embedding_dimensions,
    )
    return client.embed_documents(texts)


async def embed_texts(texts: list[str], *, org_id: str | None, purpose: str = "rag_index") -> Embedded | None:
    """Embed `texts` under the organisation's data mode; None = no embeddings (use TF-IDF)."""
    if not texts or not _has_embedding_support():
        return None
    try:
        session = await open_session(org_id, stable=True)
    except PolicyOff:
        return None
    outbound = session.outbound_texts(texts)
    tally = CallTally()
    session.sent(outbound, tally)
    try:
        vectors = await asyncio.to_thread(_client_embed, outbound)
    except Exception as exc:
        logger.warning("RAG embedding generation failed, using TF-IDF only: %s", exc)
        audit.persist_call_log(org_id=session.org_id, job_id=None, task=purpose, model=get_settings().rag_embedding_model,
                               res=None, ok=False, error=type(exc).__name__, tally=tally)
        return None
    audit.persist_call_log(org_id=session.org_id, job_id=None, task=purpose, model=get_settings().rag_embedding_model,
                           res=None, ok=True, error=None, tally=tally)
    return Embedded(vectors, embedding_tag(session.mode))
