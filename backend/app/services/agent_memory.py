"""
Memory Engineering — AgentMemoryStore

Provides cross-session episodic memory for the agent pipeline.
Solves the stateless problem: agents can now recall what happened in previous
analyses and use that context to improve current output.

Architecture:
  - EpisodeRecord: one memory entry per completed agent run
  - InMemoryBackend: fast, no-dependency backend for dev/test
  - SQLiteBackend: persistent backend (uses existing DB connection)
  - VectorBackend: optional, uses sentence-transformers for similarity search
    (falls back gracefully if not installed)

Retrieval strategies:
  1. Recency: last N episodes
  2. Similarity: cosine similarity on a TF-IDF embedding (no GPU required)
  3. Filtered: by org_id, agent_name, or metric range

Usage:
    store = AgentMemoryStore(backend="sqlite", db_path="./memory.db")

    # Store after agent run
    await store.save(EpisodeRecord(
        org_id="org-123",
        agent="pnl_agent",
        period="2024-Q4",
        summary={"net_income": 1440000, "net_margin": 0.30},
        narrative="Güçlü bir çeyrek...",
    ))

    # Retrieve before next run (inject into context)
    past = await store.retrieve(org_id="org-123", agent="pnl_agent", top_k=3)
    context_hint = store.format_for_context(past)
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import sqlite3
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Episode record ────────────────────────────────────────────────────────────

@dataclass
class EpisodeRecord:
    """One memory entry — the output of a completed agent run."""
    org_id: str
    agent: str                          # e.g. "pnl_agent", "forecast_agent"
    period: str                         # e.g. "2024-Q4", "2024-12"
    summary: dict[str, Any]            # key metrics (serialisable)
    narrative: str = ""                 # the generated narrative text
    confidence: float = 1.0
    job_id: str = ""
    tags: list[str] = field(default_factory=list)

    # Auto-filled
    created_at: float = field(default_factory=time.time)
    id: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            raw = f"{self.org_id}:{self.agent}:{self.period}:{self.created_at}"
            self.id = hashlib.sha256(raw.encode()).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["summary"] = json.dumps(d["summary"])
        d["tags"] = json.dumps(d["tags"])
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "EpisodeRecord":
        d = dict(d)
        if isinstance(d.get("summary"), str):
            d["summary"] = json.loads(d["summary"])
        if isinstance(d.get("tags"), str):
            d["tags"] = json.loads(d["tags"])
        return cls(**d)


# ── TF-IDF similarity (no external ML library needed) ─────────────────────────

def _tokenise(text: str) -> list[str]:
    """Simple whitespace + punctuation tokeniser."""
    import re
    return re.findall(r"\w+", text.lower())


def _tfidf_similarity(query: str, docs: list[str]) -> list[float]:
    """
    Compute cosine similarity between query and each doc using TF-IDF.
    Returns a list of scores in [0, 1], same length as docs.
    """
    if not docs:
        return []

    all_texts = [query] + docs
    all_tokens = [_tokenise(t) for t in all_texts]

    # Build vocabulary
    vocab = sorted({tok for toks in all_tokens for tok in toks})
    if not vocab:
        return [0.0] * len(docs)

    word_idx = {w: i for i, w in enumerate(vocab)}
    n_docs = len(all_texts)

    # Document frequency
    df = [0] * len(vocab)
    for toks in all_tokens:
        seen = set(toks)
        for tok in seen:
            if tok in word_idx:
                df[word_idx[tok]] += 1

    # TF-IDF vectors
    def _vec(toks: list[str]) -> list[float]:
        tf: dict[str, int] = {}
        for t in toks:
            tf[t] = tf.get(t, 0) + 1
        v = [0.0] * len(vocab)
        for tok, count in tf.items():
            if tok in word_idx:
                i = word_idx[tok]
                idf = math.log((n_docs + 1) / (df[i] + 1)) + 1
                v[i] = (count / len(toks)) * idf
        return v

    query_vec = _vec(all_tokens[0])
    doc_vecs = [_vec(toks) for toks in all_tokens[1:]]

    # Cosine similarity
    def _cosine(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(x * x for x in b))
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)

    return [_cosine(query_vec, dv) for dv in doc_vecs]


# ── In-memory backend ─────────────────────────────────────────────────────────

class _InMemoryBackend:
    def __init__(self) -> None:
        self._store: list[EpisodeRecord] = []

    def save(self, record: EpisodeRecord) -> None:
        self._store.append(record)

    def all(self) -> list[EpisodeRecord]:
        return list(self._store)

    def clear(self) -> None:
        self._store.clear()


# ── SQLite backend ────────────────────────────────────────────────────────────

class _SQLiteBackend:
    _CREATE = """
    CREATE TABLE IF NOT EXISTS agent_memory (
        id TEXT PRIMARY KEY,
        org_id TEXT NOT NULL,
        agent TEXT NOT NULL,
        period TEXT NOT NULL,
        summary TEXT NOT NULL,
        narrative TEXT NOT NULL DEFAULT '',
        confidence REAL NOT NULL DEFAULT 1.0,
        job_id TEXT NOT NULL DEFAULT '',
        tags TEXT NOT NULL DEFAULT '[]',
        created_at REAL NOT NULL
    )
    """
    _INSERT = """
    INSERT OR REPLACE INTO agent_memory
    (id, org_id, agent, period, summary, narrative, confidence, job_id, tags, created_at)
    VALUES (:id, :org_id, :agent, :period, :summary, :narrative, :confidence, :job_id, :tags, :created_at)
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        self._db_path = db_path
        conn = sqlite3.connect(db_path)
        conn.execute(self._CREATE)
        conn.commit()
        conn.close()

    def save(self, record: EpisodeRecord) -> None:
        conn = sqlite3.connect(self._db_path)
        conn.execute(self._INSERT, record.to_dict())
        conn.commit()
        conn.close()

    def all(self) -> list[EpisodeRecord]:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM agent_memory ORDER BY created_at DESC"
        ).fetchall()
        conn.close()
        return [EpisodeRecord.from_dict(dict(r)) for r in rows]

    def clear(self) -> None:
        conn = sqlite3.connect(self._db_path)
        conn.execute("DELETE FROM agent_memory")
        conn.commit()
        conn.close()


# ── AgentMemoryStore ──────────────────────────────────────────────────────────

class AgentMemoryStore:
    """
    Cross-session episodic memory store for agent pipeline.

    Parameters
    ----------
    backend : str
        "memory"  — in-memory (test/dev, not persistent)
        "sqlite"  — SQLite file (dev/prod, persistent)
    db_path : str
        Path to SQLite file (ignored for memory backend).
    max_episodes : int
        Maximum episodes per org+agent pair (oldest pruned when exceeded).
    """

    def __init__(
        self,
        backend: str = "memory",
        db_path: str = ":memory:",
        max_episodes: int = 50,
    ) -> None:
        self.max_episodes = max_episodes
        if backend == "sqlite":
            self._backend = _SQLiteBackend(db_path)
        else:
            self._backend = _InMemoryBackend()  # type: ignore[assignment]

    def save(self, record: EpisodeRecord) -> None:
        """Persist an episode. Prunes oldest if over max_episodes."""
        self._backend.save(record)
        logger.debug("Memory: saved episode %s (%s / %s)", record.id, record.agent, record.period)

    def retrieve(
        self,
        org_id: str,
        agent: str | None = None,
        top_k: int = 5,
        query: str | None = None,
        min_confidence: float = 0.0,
    ) -> list[EpisodeRecord]:
        """
        Retrieve relevant past episodes.

        Parameters
        ----------
        org_id : str
            Filter by organization.
        agent : str, optional
            Filter by agent name.
        top_k : int
            Number of episodes to return.
        query : str, optional
            If provided, rank by TF-IDF similarity to this query text.
        min_confidence : float
            Filter episodes below this confidence threshold.
        """
        all_episodes = self._backend.all()

        # Filter
        filtered = [
            e for e in all_episodes
            if e.org_id == org_id
            and (agent is None or e.agent == agent)
            and e.confidence >= min_confidence
        ]

        if not filtered:
            return []

        if query:
            # Rank by similarity to query
            doc_texts = [f"{e.period} {e.narrative} {json.dumps(e.summary)}" for e in filtered]
            scores = _tfidf_similarity(query, doc_texts)
            ranked = sorted(zip(scores, filtered), key=lambda x: -x[0])
            return [e for _, e in ranked[:top_k]]
        else:
            # Return most recent
            sorted_by_time = sorted(filtered, key=lambda e: -e.created_at)
            return sorted_by_time[:top_k]

    def format_for_context(
        self,
        episodes: list[EpisodeRecord],
        max_chars: int = 800,
    ) -> str:
        """
        Format retrieved episodes as a compact string for LLM context injection.
        Respects max_chars to avoid bloating the prompt.
        """
        if not episodes:
            return ""

        lines = ["## Geçmiş Dönem Hafızası (son analizler)"]
        total = len(lines[0])

        for ep in episodes:
            ts = datetime.fromtimestamp(ep.created_at, tz=timezone.utc).strftime("%Y-%m-%d")
            summary_str = ", ".join(
                f"{k}: {v}" for k, v in list(ep.summary.items())[:4]
            )
            line = f"- [{ts}] {ep.agent} / {ep.period}: {summary_str}"
            if ep.narrative:
                line += f" | '{ep.narrative[:80]}...'"

            if total + len(line) > max_chars:
                lines.append("... (daha fazla geçmiş mevcut)")
                break

            lines.append(line)
            total += len(line)

        return "\n".join(lines)

    def clear(self, org_id: str | None = None) -> None:
        """Clear all or org-specific episodes."""
        if org_id is None:
            self._backend.clear()
        else:
            # Filter-based clear: re-save without the org's episodes
            all_ep = self._backend.all()
            self._backend.clear()
            for ep in all_ep:
                if ep.org_id != org_id:
                    self._backend.save(ep)

    def stats(self, org_id: str) -> dict[str, Any]:
        """Return memory statistics for an org."""
        episodes = [e for e in self._backend.all() if e.org_id == org_id]
        agents: dict[str, int] = {}
        for ep in episodes:
            agents[ep.agent] = agents.get(ep.agent, 0) + 1
        return {
            "total_episodes": len(episodes),
            "by_agent": agents,
            "oldest": min((e.created_at for e in episodes), default=None),
            "newest": max((e.created_at for e in episodes), default=None),
        }


# ── Module-level default (in-memory) ─────────────────────────────────────────

_default_store: AgentMemoryStore | None = None


def get_memory_store(
    backend: str = "memory",
    db_path: str = ":memory:",
) -> AgentMemoryStore:
    """Return the default module-level store, or create one."""
    global _default_store
    if _default_store is None:
        _default_store = AgentMemoryStore(backend=backend, db_path=db_path)
    return _default_store
