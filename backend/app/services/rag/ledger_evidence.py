"""Chat evidence read from the company ledger (G9).

The chat's transaction evidence used to be the RAG chunks of the *active* CFO job,
so anything uploaded earlier was invisible to it even though the ledger holds it.
Here the evidence is the ledger itself: active rows of the organisation, matched to
the question by the words they share (counterparty, description, category).

Matching is lexical on purpose: it is deterministic, needs no model key, and every
citation is a real ledger row with its real amount, so the grounding validator can
check an answer's figures against it.
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.turkish import fold
from app.models.canonical_transaction import CanonicalTransaction as CT
from app.platform.contracts import EvidenceBundle, EvidenceCitation

SOURCE_TYPE = "ledger_row"
VERSION = "ledger_v1"

# Rows whose words are scanned for one question. Narrow columns only, newest first,
# so a large ledger is bounded and the bound is not arbitrary.
_SCAN_LIMIT = 50_000
_MIN_SCORE = 0.34
_STOPWORDS = frozenset({
    "kadar", "nedir", "bana", "goster", "icin", "hangi", "nasil", "var", "yok", "ise",
    "what", "how", "much", "the", "for", "are", "does", "show", "give", "has", "have",
})


def _tokens(text: str | None) -> list[str]:
    return re.findall(r"[a-z0-9]+", fold(text))


def _question_words(question: str) -> list[str]:
    seen: dict[str, None] = {}
    for w in _tokens(question):
        if len(w) >= 3 and w not in _STOPWORDS:
            seen.setdefault(w)
    return list(seen)


def _stem(word: str) -> str:
    """Turkish suffixes pile onto names ("ABC Holding'den"); compare a stable prefix."""
    return word[:5] if len(word) > 5 else word


def _score(words: list[str], haystack: set[str]) -> float:
    if not words:
        return 0.0
    hit = sum(1 for w in words if any(t.startswith(_stem(w)) for t in haystack))
    return hit / len(words)


def _preview(row: CT) -> str:
    when = row.transaction_date.date().isoformat() if row.transaction_date else "?"
    text = (row.description or "").strip()
    return (
        f"{when} {row.direction} {row.amount_cents / 100:.2f} {row.currency} "
        f"{row.counterparty or '-'} · {text[:120]} [{row.basis}]"
    )


async def retrieve_ledger_evidence(
    *, db: AsyncSession, org_id: str, query: str, top_k: int = 3
) -> EvidenceBundle:
    """The ledger rows of this organisation that best match the question."""
    words = _question_words(query)
    empty = EvidenceBundle(query=query, org_id=org_id, citations=[], job_scope="org_wide",
                           retriever_version=VERSION)
    if not words or not org_id:
        return empty

    scanned = (await db.execute(
        select(CT.id, CT.counterparty, CT.description, CT.category)
        .where(CT.org_id == str(org_id), CT.ledger_status == "active")
        .order_by(CT.transaction_date.desc(), CT.id)
        .limit(_SCAN_LIMIT)
    )).all()

    ranked: list[tuple[float, str]] = []
    for row_id, counterparty, description, category in scanned:
        s = _score(words, set(_tokens(f"{counterparty or ''} {description or ''} {category or ''}")))
        if s >= _MIN_SCORE:
            ranked.append((s, row_id))
    ranked.sort(key=lambda r: -r[0])      # stable: ties keep newest first
    best = ranked[:top_k]
    if not best:
        return empty

    rows = {r.id: r for r in (await db.execute(select(CT).where(CT.id.in_([i for _, i in best])))).scalars()}
    citations = [
        EvidenceCitation(
            job_id=rows[row_id].source_job_id, chunk_index=rank, source_type=SOURCE_TYPE,
            score=score, preview=_preview(rows[row_id]),
        )
        for rank, (score, row_id) in enumerate(best, start=1)
        if row_id in rows
    ]
    return EvidenceBundle(query=query, org_id=org_id, citations=citations, job_scope="org_wide",
                          retriever_version=VERSION)
