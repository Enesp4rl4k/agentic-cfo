"""Erase the personal data that lives OUTSIDE the SQL tables: caches, chat history, agent memory.

`org_erasure` derives its table scope from the SQLAlchemy metadata, so it cannot see these:

* Redis: chat history `conv:{user}:{session}` (7 days, sliding), the company context, semantic snapshots,
  the morning and Monday briefings, temporal events, the analytics cache, a job's CEO result `ceo:{job}`
  and alert acknowledgements `ack:{job}:*`;
* the in-process fallbacks of the chat history and the cache (what a worker holds when Redis is down);
* the agent's episodic memory, which keeps a narrative per organisation in a table the ORM does not know
  (`agent_memory_episodes` on PostgreSQL, `agent_memory` on SQLite, a list in memory otherwise).

Where each part runs (see `privacy.erasure_cleanup` for the order of an erasure):

* The Postgres agent memory is erased INSIDE the erase transaction, and a failure aborts the whole erasure
  (`AgentMemoryDeleteError`): nothing is committed, no file is touched, the request is left `failed` with a fixed
  code an operator can see, and the executor retries it.
* Everything that is not transactional runs AFTER the commit from the durable cleanup plan (`cleanup_ephemeral`): the
  in-process caches, agent memory on SQLite / in memory, and one Redis SCAN pass (tried twice). A failure there
  leaves the plan to be run again (`redis_failed`, `agent_memory_failed`); Redis keys expire by themselves anyway.
* Every id used as a search needle must be a UUID (`erasure_cleanup.require_ids`); anything else raises before a single
  key is looked at, so a missing id can never become the substring "None" swept across other tenants.
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from typing import Any

from sqlalchemy import column, create_engine, delete, inspect, table
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.privacy.erasure_cleanup import InvalidTargetError, require_ids, valid_id

logger = logging.getLogger(__name__)

# The agent memory tables are created by `agent_memory` with its own DDL, not by the ORM metadata: a Core handle.
_PG_TABLE = table("agent_memory_episodes", column("org_id"))
_SQLITE_TABLE = table("agent_memory", column("org_id"))


def _matcher(org_id: str, user_ids: Iterable[str], job_ids: Iterable[str]) -> Callable[[str], bool]:
    """One predicate for every key of the organisation: a single SCAN pass instead of one full-keyspace SCAN per
    pattern. HARD GUARD: every id must be a UUID, otherwise this raises and nothing is ever matched."""
    users, jobs = list(user_ids), list(job_ids)
    require_ids(org_id, users, jobs)
    needles = tuple(dict.fromkeys([org_id, *jobs]))
    prefixes = tuple(f"conv:{uid}:" for uid in users)

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

    require_ids(org_id, user_ids, job_ids)
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
    """The IN-TRANSACTION part: one organisation's PostgreSQL episodes (Core statement, no SQL text), in the erasure's
    own transaction so a failure rolls everything back. Other backends are not transactional: they run after the
    commit (`_agent_memory_delete_local`). Raises `AgentMemoryDeleteError`; a missing table is not a failure."""
    from app.services import agent_memory as am

    require_ids(org_id)
    backend: Any = am.get_memory_store()._backend
    if isinstance(backend, am._InMemoryBackend | am._SQLiteBackend):
        return 0
    try:
        # The table is created lazily by the store: no table, nothing to erase (and no failed statement in the transaction).
        exists = await db.run_sync(lambda sync: inspect(sync.connection()).has_table(_PG_TABLE.name))
        if not exists:
            return 0
        result: Any = await db.execute(delete(_PG_TABLE).where(_PG_TABLE.c.org_id == org_id))
        return int(result.rowcount)
    except Exception as exc:
        logger.warning("ephemeral erasure: agent memory failed (%s)", type(exc).__name__)
        raise AgentMemoryDeleteError("agent memory delete failed") from exc


def _agent_memory_delete_local(org_id: str) -> int:
    """The AFTER-COMMIT part: the in-memory list and the SQLite file (not part of any transaction)."""
    from app.services import agent_memory as am

    require_ids(org_id)
    backend: Any = am.get_memory_store()._backend
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
    return 0


class CheckpointDeleteError(RuntimeError):
    """The LangGraph checkpoints of an organisation could not be deleted: the erasure aborts, like agent memory."""


async def _checkpoints_delete(db: AsyncSession, org_id: str) -> int:
    """The organisation's checkpoint threads (`<org_id>:<job_id>`) in the library's Postgres tables, inside the
    erase transaction. Other backends hold checkpoints in memory or a local SQLite file, not in this database."""
    from app.agents.checkpointer import erase_org_checkpoints

    if db.bind is None or db.bind.dialect.name != "postgresql":
        return 0
    try:
        return await erase_org_checkpoints(db, org_id)
    except Exception as exc:
        logger.warning("ephemeral erasure: checkpoints failed (%s)", type(exc).__name__)
        raise CheckpointDeleteError("checkpoint delete failed") from exc


async def erase_org_in_transaction(db: AsyncSession, org_id: str) -> dict[str, int]:
    """What may run inside the erase transaction: the Postgres agent memory and the LangGraph checkpoints.
    Raises `AgentMemoryDeleteError` / `CheckpointDeleteError`."""
    return {
        "agent_memory_deleted": await _agent_memory_delete(db, org_id),
        "checkpoints_deleted": await _checkpoints_delete(db, org_id),
    }


async def cleanup_ephemeral(org_id: str, user_ids: list[str], job_ids: list[str]) -> dict[str, int]:
    """The after-commit part: in-process caches, non-transactional agent memory, Redis. Counts only. Raises only
    `InvalidTargetError` (before doing anything); other failures are counted (`*_failed`) and the plan runs again."""
    require_ids(org_id, user_ids, job_ids)
    counts: dict[str, int] = {"memory_dropped": _memory_delete(org_id, user_ids, job_ids)}
    try:
        counts["agent_memory_deleted"] = _agent_memory_delete_local(org_id)
    except Exception as exc:
        logger.warning("ephemeral erasure: local agent memory failed (%s)", type(exc).__name__)
        counts["agent_memory_failed"] = 1
    counts.update(await sweep_org_redis(org_id, user_ids, job_ids))
    return counts


async def erase_user_ephemeral(user_id: str) -> dict[str, int]:
    """Erase one person's chat history (Redis and the in-process fallback)."""
    if not valid_id(user_id):
        raise InvalidTargetError("user id is not a UUID")
    prefix = f"conv:{user_id}:"
    counts = await _redis_sweep(lambda key: key.startswith(prefix))
    from app.services import conversation_memory as conv

    for key in [k for k in conv._fallback_store if k.startswith(prefix)]:
        conv._fallback_store.pop(key, None)
        counts["memory_dropped"] = counts.get("memory_dropped", 0) + 1
    return counts
