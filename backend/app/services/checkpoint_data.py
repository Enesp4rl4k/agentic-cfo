"""The checkpoint tables as DATA: names, thread ids, erasure and retention (services layer).

The saver itself lives in `app.agents.checkpointer`; organisation erasure and the retention job (services) need only
these table names and statements, and a lower layer must not import `app.agents`.
"""
from __future__ import annotations

from typing import Any

# Created and migrated by the langgraph library, not by Alembic: the schema-drift check ignores them.
CHECKPOINT_DATA_TABLES = ("checkpoints", "checkpoint_blobs", "checkpoint_writes")
LIBRARY_TABLES = (*CHECKPOINT_DATA_TABLES, "checkpoint_migrations")


def thread_key(org_id: str | None, job_id: str) -> str:
    """The checkpoint thread of one run: namespaced by organisation (`-` when a run has none, tests only)."""
    return f"{org_id or '-'}:{job_id}"


def thread_like(org_id: str) -> str:
    """LIKE pattern selecting every thread of one organisation (`org_id` must be a UUID: no wildcards inside)."""
    return f"{org_id}:%"


async def erase_org_checkpoints(db: Any, org_id: str) -> int:
    """Delete one organisation's checkpoints inside the caller's transaction (the erase transaction).

    Core statements on the library's tables, filtered by the organisation prefix of the thread id. A missing table
    (the saver never ran on this database) is nothing to erase, not a failure. Returns rows deleted from
    `checkpoints`."""
    from sqlalchemy import column, delete, inspect, table

    from app.services.privacy.erasure_cleanup import require_ids

    require_ids(org_id)
    present = await db.run_sync(
        lambda sync: {t for t in CHECKPOINT_DATA_TABLES if inspect(sync.connection()).has_table(t)}
    )
    deleted = 0
    for name in CHECKPOINT_DATA_TABLES:
        if name not in present:
            continue
        t = table(name, column("thread_id"))
        result: Any = await db.execute(delete(t).where(t.c.thread_id.like(thread_like(org_id))))
        if name == "checkpoints":
            deleted = int(result.rowcount)
    return deleted


async def purge_old_checkpoints(db: Any, *, days: int, dry_run: bool, now: Any) -> int:
    """Retention: delete the threads whose newest checkpoint is older than `days`. Postgres only; returns threads.

    A checkpoint only serves to resume an interrupted run; a thread idle for `days` will not be resumed. The age is
    the checkpoint's own `ts` (the library keeps no column for it)."""
    from datetime import timedelta

    from sqlalchemy import inspect, text

    if days <= 0 or db.bind is None or db.bind.dialect.name != "postgresql":
        return 0
    present = await db.run_sync(lambda sync: inspect(sync.connection()).has_table("checkpoints"))
    if not present:
        return 0
    cutoff = now - timedelta(days=days)
    ids = [
        r[0]
        for r in (
            await db.execute(
                text(
                    "SELECT thread_id FROM checkpoints GROUP BY thread_id "
                    "HAVING max((checkpoint->>'ts')::timestamptz) < :cutoff"
                ),
                {"cutoff": cutoff},
            )
        ).all()
    ]
    if ids and not dry_run:
        for name in CHECKPOINT_DATA_TABLES:
            await db.execute(text(f"DELETE FROM {name} WHERE thread_id = ANY(:ids)"), {"ids": ids})
    return len(ids)
