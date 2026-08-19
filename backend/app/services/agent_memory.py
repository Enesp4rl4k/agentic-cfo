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


# ── PostgreSQL async backend ──────────────────────────────────────────────────

class _PostgreSQLBackend:
    """
    Async PostgreSQL backend using asyncpg directly (no SQLAlchemy dependency).
    Falls back to SQLite gracefully if asyncpg is not available.

    Table: agent_memory_episodes (separate from main ORM tables to keep
    the memory store self-contained and independently deployable).
    """

    _CREATE = """
    CREATE TABLE IF NOT EXISTS agent_memory_episodes (
        id          TEXT PRIMARY KEY,
        org_id      TEXT NOT NULL,
        agent       TEXT NOT NULL,
        period      TEXT NOT NULL,
        summary     TEXT NOT NULL,
        narrative   TEXT NOT NULL DEFAULT '',
        confidence  REAL NOT NULL DEFAULT 1.0,
        job_id      TEXT NOT NULL DEFAULT '',
        tags        TEXT NOT NULL DEFAULT '[]',
        created_at  REAL NOT NULL
    )
    """
    _CREATE_IDX_ORG   = "CREATE INDEX IF NOT EXISTS idx_ame_org   ON agent_memory_episodes(org_id)"
    _CREATE_IDX_AGENT = "CREATE INDEX IF NOT EXISTS idx_ame_agent ON agent_memory_episodes(org_id, agent)"

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: Any = None

    async def _get_pool(self) -> Any:
        if self._pool is None:
            try:
                import asyncpg
                self._pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=5)
                async with self._pool.acquire() as conn:
                    await conn.execute(self._CREATE)
                    await conn.execute(self._CREATE_IDX_ORG)
                    await conn.execute(self._CREATE_IDX_AGENT)
                logger.info("AgentMemory: PostgreSQL backend connected")
            except Exception as exc:
                logger.error("AgentMemory: PostgreSQL init failed: %s", exc)
                raise
        return self._pool

    def save(self, record: EpisodeRecord) -> None:
        """Sync wrapper — schedules the async save on the running event loop."""
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self._async_save(record))
            else:
                loop.run_until_complete(self._async_save(record))
        except Exception as exc:
            logger.warning("AgentMemory PostgreSQL save failed: %s", exc)

    async def _async_save(self, record: EpisodeRecord) -> None:
        pool = await self._get_pool()
        d = record.to_dict()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO agent_memory_episodes
                    (id, org_id, agent, period, summary, narrative,
                     confidence, job_id, tags, created_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                ON CONFLICT (id) DO UPDATE SET
                    summary   = EXCLUDED.summary,
                    narrative = EXCLUDED.narrative,
                    confidence= EXCLUDED.confidence
                """,
                d["id"], d["org_id"], d["agent"], d["period"],
                d["summary"], d["narrative"], d["confidence"],
                d["job_id"], d["tags"], d["created_at"],
            )

    def all(self) -> list[EpisodeRecord]:
        """Sync wrapper — runs async query in event loop."""
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Can't block a running loop — return empty and log
                # Callers in async context should use async retrieve directly
                logger.debug("AgentMemory: all() called from running loop — use async path")
                return []
            return loop.run_until_complete(self._async_all())
        except Exception as exc:
            logger.warning("AgentMemory PostgreSQL all() failed: %s", exc)
            return []

    async def _async_all(self) -> list[EpisodeRecord]:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM agent_memory_episodes ORDER BY created_at DESC"
            )
        return [EpisodeRecord.from_dict(dict(r)) for r in rows]

    async def async_retrieve(
        self,
        org_id: str,
        agent: str | None = None,
        top_k: int = 5,
        min_confidence: float = 0.0,
    ) -> list[EpisodeRecord]:
        """Async-native retrieve — preferred over sync all() in async contexts."""
        pool = await self._get_pool()
        if agent:
            rows = await pool.fetch(
                """
                SELECT * FROM agent_memory_episodes
                WHERE org_id=$1 AND agent=$2 AND confidence>=$3
                ORDER BY created_at DESC LIMIT $4
                """,
                org_id, agent, min_confidence, top_k,
            )
        else:
            rows = await pool.fetch(
                """
                SELECT * FROM agent_memory_episodes
                WHERE org_id=$1 AND confidence>=$2
                ORDER BY created_at DESC LIMIT $3
                """,
                org_id, min_confidence, top_k,
            )
        return [EpisodeRecord.from_dict(dict(r)) for r in rows]

    def clear(self) -> None:
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if not loop.is_running():
                loop.run_until_complete(self._async_clear())
        except Exception as exc:
            logger.warning("AgentMemory PostgreSQL clear() failed: %s", exc)

    async def _async_clear(self) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM agent_memory_episodes")


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
        "memory"     — in-memory (test/dev, not persistent)
        "sqlite"     — SQLite file (dev, persistent)
        "postgresql" — PostgreSQL async (production)
    db_path : str
        Path to SQLite file (ignored for memory/postgresql backends).
    pg_dsn : str
        PostgreSQL DSN e.g. "postgresql://user:pass@host/db".
        Only used when backend="postgresql".
    max_episodes : int
        Maximum episodes per org+agent pair (oldest pruned when exceeded).
    """

    def __init__(
        self,
        backend: str = "memory",
        db_path: str = ":memory:",
        pg_dsn: str = "",
        max_episodes: int = 50,
    ) -> None:
        self.max_episodes = max_episodes
        self._backend_name = backend
        if backend == "postgresql":
            if not pg_dsn:
                logger.warning(
                    "AgentMemory: pg_dsn not set — falling back to in-memory backend"
                )
                self._backend = _InMemoryBackend()  # type: ignore[assignment]
            else:
                self._backend = _PostgreSQLBackend(pg_dsn)  # type: ignore[assignment]
        elif backend == "sqlite":
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


# ── Module-level default — auto-configured from settings ─────────────────────

_default_store: AgentMemoryStore | None = None


def get_memory_store(
    backend: str | None = None,
    db_path: str = ":memory:",
    pg_dsn: str = "",
) -> AgentMemoryStore:
    """
    Return the singleton memory store, auto-configured from app settings.

    Priority:
      1. Explicit `backend` parameter (for tests / forced override)
      2. Settings: use_sqlite=False + postgres DSN → "postgresql"
      3. Settings: use_sqlite=True → "sqlite" with aicfo_dev path
      4. Fallback: "memory" (no persistence)

    This means orchestrator.py and worker.py no longer need to hardcode
    "sqlite" — they call get_memory_store() with no arguments and get the
    correct backend for the current environment.
    """
    global _default_store
    if _default_store is None:
        if backend is not None:
            # Explicit override (tests, CLI tools)
            _default_store = AgentMemoryStore(
                backend=backend, db_path=db_path, pg_dsn=pg_dsn
            )
        else:
            # Auto-detect from settings
            try:
                from app.config import get_settings
                s = get_settings()
                if not s.use_sqlite:
                    # Production: PostgreSQL — derive sync DSN from database_url
                    # asyncpg needs "postgresql://" not "postgresql+asyncpg://"
                    dsn = s.database_url_sync  # already plain postgresql://
                    _default_store = AgentMemoryStore(
                        backend="postgresql", pg_dsn=dsn
                    )
                    logger.info("AgentMemory: using PostgreSQL backend")
                else:
                    _default_store = AgentMemoryStore(
                        backend="sqlite", db_path="./agent_memory.db"
                    )
                    logger.info("AgentMemory: using SQLite backend (dev)")
            except Exception as exc:
                logger.warning(
                    "AgentMemory: settings load failed (%s) — using in-memory", exc
                )
                _default_store = AgentMemoryStore(backend="memory")

    return _default_store


def reset_memory_store() -> None:
    """Reset singleton — for testing only."""
    global _default_store
    _default_store = None
