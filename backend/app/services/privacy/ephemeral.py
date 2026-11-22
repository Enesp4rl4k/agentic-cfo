"""Erase the personal data that lives OUTSIDE the SQL tables: caches, chat history, agent memory.

`org_erasure` derives its table scope from the SQLAlchemy metadata, so it cannot see these:

* Redis: chat history `conv:{user}:{session}` (7 days, sliding), the company context, semantic snapshots,
  the morning and Monday briefings, temporal events, the analytics cache, a job's CEO result `ceo:{job}`
  and alert acknowledgements `ack:{job}:*`;
* the in-process fallbacks of the chat history and the cache (what a worker holds when Redis is down);
* the agent's episodic memory, which keeps a narrative per organisation in a table the ORM does not know
  (`agent_memory_episodes` on PostgreSQL, `agent_memory` on SQLite, a list in memory otherwise).

Everything here is derived data: losing it costs a recomputation, so it is erased before the database commit and
a failure is reported in the counts instead of blocking the erasure. Whatever Redis could not delete expires by
its own time-to-live (at most the 7 days of the chat history) and the report says so.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from sqlalchemy import column, create_engine, delete, inspect, table
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# The agent memory tables are created by `agent_memory` with its own DDL, not by the ORM metadata: a Core handle.
_PG_TABLE = table("agent_memory_episodes", column("org_id"))
_SQLITE_TABLE = table("agent_memory", column("org_id"))

# Keys that name an organisation, a user or a job in the middle or at the end are found by the generic sweeps below;
# these prefixes are the ones we know and test.
ORG_KEY_PREFIXES = ("company_context:", "morning_brief:", "monday_briefing:", "semantic:", "temporal:")


def org_patterns(org_id: str, user_ids: Iterable[str], job_ids: Iterable[str]) -> list[str]:
    """Redis SCAN patterns that cover an organisation's, its members' and its jobs' keys."""
    patterns = [f"{p}{org_id}*" for p in ORG_KEY_PREFIXES]
    patterns.append(f"*{org_id}*")  # the analytics cache and whatever a later feature keys by the id
    patterns += [f"conv:{uid}:*" for uid in user_ids]
    for jid in job_ids:
        patterns += [f"ceo:{jid}", f"ack:{jid}:*", f"*{jid}*"]
    return list(dict.fromkeys(patterns))


async def _redis_delete(patterns: list[str]) -> dict[str, int]:
    from app.core.redis_client import get_redis, mark_unavailable

    client = await get_redis()
    if client is None:
        return {}
    deleted = 0
    try:
        for pattern in patterns:
            async for key in client.scan_iter(match=pattern, count=200):
                await client.delete(key)
                deleted += 1
    except Exception as exc:
        mark_unavailable(exc)
        logger.warning("ephemeral erasure: Redis failed (%s); the keys expire by their time-to-live", exc)
        return {"redis_deleted": deleted, "redis_failed": 1}
    return {"redis_deleted": deleted}


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


async def _agent_memory_delete(db: AsyncSession, org_id: str) -> int:
    """Remove one organisation's episodes from whichever backend the store uses (Core statements, no SQL text)."""
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
        logger.warning("ephemeral erasure: agent memory failed (%s)", exc)
        return -1


async def erase_org_ephemeral(
    db: AsyncSession, org_id: str, user_ids: list[str], job_ids: list[str]
) -> dict[str, int]:
    """Erase caches, chat history and agent memory for one organisation. Never raises; counts only."""
    counts = await _redis_delete(org_patterns(org_id, user_ids, job_ids))
    counts["memory_dropped"] = _memory_delete(org_id, user_ids, job_ids)
    counts["agent_memory_deleted"] = await _agent_memory_delete(db, org_id)
    return counts


async def erase_user_ephemeral(user_id: str) -> dict[str, int]:
    """Erase one person's chat history (Redis and the in-process fallback)."""
    counts = await _redis_delete([f"conv:{user_id}:*"])
    from app.services import conversation_memory as conv

    prefix = f"conv:{user_id}:"
    for key in [k for k in conv._fallback_store if k.startswith(prefix)]:
        conv._fallback_store.pop(key, None)
        counts["memory_dropped"] = counts.get("memory_dropped", 0) + 1
    return counts
