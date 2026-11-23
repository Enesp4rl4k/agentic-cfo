"""Erase the personal data that lives OUTSIDE the SQL tables: caches, chat history, agent memory.

`org_erasure` derives its table scope from the SQLAlchemy metadata, so it cannot see these:

* Redis: chat history `conv:{user}:{session}` (7 days, sliding), the company context, semantic snapshots,
  the morning and Monday briefings, temporal events, the analytics cache, a job's CEO result `ceo:{job}`
  and alert acknowledgements `ack:{job}:*`;
* the in-process fallbacks of the chat history and the cache (what a worker holds when Redis is down);
* the agent's episodic memory, which keeps a narrative per organisation in a table the ORM does not know
  (`agent_memory_episodes` on PostgreSQL, `agent_memory` on SQLite, a list in memory otherwise).

Two different failure policies, on purpose:

* Redis and the in-process caches are derived data: they are swept AFTER the database commit (one SCAN pass), tried
  twice, and a failure is reported in the counts (`redis_failed`, kept on the request row) instead of blocking the
  erasure. Whatever Redis could not delete expires by its own time-to-live (at most the 7 days of the chat history).
* The agent memory holds a narrative per organisation, so it is erased INSIDE the erase transaction and a failure
  aborts the whole erasure (`AgentMemoryDeleteError`): nothing partial is reported as done, the request is marked
  `failed` with a fixed code an operator can see, and the executor retries it.
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from typing import Any

from sqlalchemy import column, create_engine, delete, inspect, table
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# The agent memory tables are created by `agent_memory` with its own DDL, not by the ORM metadata: a Core handle.
_PG_TABLE = table("agent_memory_episodes", column("org_id"))
_SQLITE_TABLE = table("agent_memory", column("org_id"))

def _matcher(org_id: str, user_ids: Iterable[str], job_ids: Iterable[str]) -> Callable[[str], bool]:
    """One predicate for every key of the organisation: a single SCAN pass instead of one full-keyspace SCAN per
    pattern. The ids are UUIDs from the request's own rows, so a substring test cannot match another tenant."""
    needles = tuple(dict.fromkeys([org_id, *job_ids]))
    prefixes = tuple(f"conv:{uid}:" for uid in user_ids)

    def matches(key: str) -> bool:
        return (bool(prefixes) and key.startswith(prefixes)) or any(n in key for n in needles)

    return matches


async def _sweep_once(matches: Callable[[str], bool]) -> dict[str, int]:
    from app.core.redis_client import get_redis

    client = await get_redis()
    if client is None:
        return {}
    deleted = 0
    async for raw in client.scan_iter(match="*", count=500):
        key = raw.decode() if isinstance(raw, bytes) else str(raw)
        if matches(key):
            await client.delete(raw)
            deleted += 1
    return {"redis_deleted": deleted}


async def _redis_sweep(matches: Callable[[str], bool]) -> dict[str, int]:
    """Best effort, idempotent (deleting what is already gone changes nothing), tried twice before it is reported."""
    from app.core.redis_client import mark_unavailable

    failure: Exception | None = None
    for _ in range(2):
        try:
            return await _sweep_once(matches)
        except Exception as exc:
            failure = exc
    mark_unavailable(failure)
    logger.warning("ephemeral erasure: Redis failed (%s); the keys expire by their time-to-live", failure)
    return {"redis_deleted": 0, "redis_failed": 1}


async def sweep_org_redis(org_id: str, user_ids: list[str], job_ids: list[str]) -> dict[str, int]:
    """Redis part of an organisation's erasure. Runs AFTER the database commit: it is derived data, and a long
    keyspace scan must not hold the erase transaction (and its locks) open. Never raises; counts only."""
    return await _redis_sweep(_matcher(org_id, user_ids, job_ids))


def _memory_delete(org_id: str, user_ids: list[str], job_ids: list[str]) -> int:
    from app.services import conversation_memory as conv
    from app.services.cache_service import get_cache_service

    dropped = 0
    prefixes = tuple(f"conv:{uid}:" for uid in user_ids)
    for key in [k for k in conv._fallback_store if k.startswith(prefixes)]:
        conv._fallback_store.pop(key, None)
        dropped += 1
    cache = get_cache_service()._memory_cache
    needles = [org_id, *job_ids]
    for key in [k for k in cache if any(n in k for n in needles)]:
        cache.pop(key, None)
        dropped += 1
    return dropped


class AgentMemoryDeleteError(RuntimeError):
    """The agent-memory rows of an organisation could not be deleted. Deliberately NOT swallowed: the erasure aborts
    (rolls back whole) and the request is left `failed`, so a partial erasure is never reported as done."""


async def _agent_memory_delete(db: AsyncSession, org_id: str) -> int:
    """Remove one organisation's episodes from whichever backend the store uses (Core statements, no SQL text).

    Raises `AgentMemoryDeleteError` when the statement fails; a missing table is not a failure (nothing to erase).
    """
    from app.services import agent_memory as am

    backend: Any = am.get_memory_store()._backend
    try:
        if isinstance(backend, am._InMemoryBackend):
            before = len(backend._store)
            backend._store[:] = [e for e in backend._store if e.org_id != org_id]
            return before - len(backend._store)
        if isinstance(backend, am._SQLiteBackend):
            engine = create_engine(f"sqlite:///{backend._db_path}")
            try:
                with engine.begin() as conn:
                    if not inspect(conn).has_table(_SQLITE_TABLE.name):
                        return 0
                    return int(conn.execute(delete(_SQLITE_TABLE).where(_SQLITE_TABLE.c.org_id == org_id)).rowcount)
            finally:
                engine.dispose()
        # PostgreSQL: the same database as the application, so it runs in the erasure's own transaction. The
        # table is created lazily by the store: no table, nothing to erase (and no failed statement in the transaction).
        exists = await db.run_sync(lambda sync: inspect(sync.connection()).has_table(_PG_TABLE.name))
        if not exists:
            return 0
        result: Any = await db.execute(delete(_PG_TABLE).where(_PG_TABLE.c.org_id == org_id))
        return int(result.rowcount)
    except Exception as exc:
        logger.warning("ephemeral erasure: agent memory failed (%s)", type(exc).__name__)
        raise AgentMemoryDeleteError("agent memory delete failed") from exc


async def erase_org_ephemeral(
    db: AsyncSession, org_id: str, user_ids: list[str], job_ids: list[str]
) -> dict[str, int]:
    """The in-transaction part: in-process caches and agent memory; counts only. Redis is swept after the commit
    (`sweep_org_redis`). Raises `AgentMemoryDeleteError` (see there)."""
    counts: dict[str, int] = {}
    counts["memory_dropped"] = _memory_delete(org_id, user_ids, job_ids)
    counts["agent_memory_deleted"] = await _agent_memory_delete(db, org_id)
    return counts


async def erase_user_ephemeral(user_id: str) -> dict[str, int]:
    """Erase one person's chat history (Redis and the in-process fallback)."""
    prefix = f"conv:{user_id}:"
    counts = await _redis_sweep(lambda key: key.startswith(prefix))
    from app.services import conversation_memory as conv

    for key in [k for k in conv._fallback_store if k.startswith(prefix)]:
        conv._fallback_store.pop(key, None)
        counts["memory_dropped"] = counts.get("memory_dropped", 0) + 1
    return counts
