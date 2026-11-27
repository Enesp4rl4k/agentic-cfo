"""The checkpoint tables as DATA: names, thread ids, erasure and retention (services layer).

The saver itself lives in `app.agents.checkpointer`; organisation erasure and the retention job (services) need only
these table names and statements, and a lower layer must not import `app.agents`.
"""
from __future__ import annotations

from typing import Any

# Created and migrated by the langgraph library, not by Alembic: the schema-drift check ignores them.
CHECKPOINT_DATA_TABLES = ("checkpoints", "checkpoint_blobs", "checkpoint_writes")
LIBRARY_TABLES = (*CHECKPOINT_DATA_TABLES, "checkpoint_migrations")


# A namespaced thread id starts with an organisation UUID and a colon. Anything else is un-namespaced: written before
# 2026-11-27 by a run that had no organisation, and matched by no organisation's erasure (retention removes it).
NAMESPACED_RE = "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}:"


def thread_key(org_id: str, job_id: str, run_id: str) -> str:
    """The checkpoint thread of ONE run: `<org_id>:<job_id>:<run_id>`. The only place a thread id is built.

    `org_id` must be a UUID (`InvalidTargetError` otherwise): a row that does not start with its organisation is a row
    no erasure can find. `run_id` is fresh for every run, so no run inherits another's channel values and two runs on
    one job never write the same thread. Callers go through `checkpointer.checkpoint_config`."""
    from app.services.privacy.erasure_cleanup import require_ids

    require_ids(org_id)
    return f"{org_id}:{job_id}:{run_id}"


def thread_like(org_id: str) -> str:
    """LIKE pattern selecting every thread of one organisation (`org_id` must be a UUID: no wildcards inside)."""
    return f"{org_id}:%"


async def _delete_where(db: Any, present: set[str], where: Any) -> int:
    """Delete from every checkpoint table present; returns rows deleted from `checkpoints`."""
    from sqlalchemy import column, delete, table

    deleted = 0
    for name in CHECKPOINT_DATA_TABLES:
        if name not in present:
            continue
        t = table(name, column("thread_id"))
        result: Any = await db.execute(delete(t).where(where(t.c.thread_id)))
        if name == "checkpoints":
            deleted = int(result.rowcount)
    return deleted


async def _present(db: Any) -> set[str]:
    from sqlalchemy import inspect

    return set(await db.run_sync(
        lambda sync: {t for t in CHECKPOINT_DATA_TABLES if inspect(sync.connection()).has_table(t)}
    ))


async def erase_org_checkpoints(db: Any, org_id: str, job_ids: Any = ()) -> int:
    """Delete one organisation's checkpoints inside the caller's transaction (the erase transaction).

    Core statements on the library's tables: every thread whose id starts with the organisation (`<org_id>:...`), and
    also the un-namespaced threads of the organisation's jobs that a run without an organisation wrote before
    2026-11-27 (`<job_id>...` with no colon, or `-:<job_id>...`). `job_ids` are the erased organisation's analysis
    jobs (the cleanup plan's); every id must be a UUID, so no wildcard reaches a LIKE. A missing table (the saver never
    ran on this database) is nothing to erase, not a failure. Returns rows deleted from `checkpoints`."""
    from sqlalchemy import and_, not_, or_

    from app.services.privacy.erasure_cleanup import require_ids

    jobs = list(job_ids)
    require_ids(org_id, jobs)
    present = await _present(db)
    deleted = await _delete_where(db, present, lambda c: c.like(thread_like(org_id)))
    if jobs:
        def legacy(c: Any) -> Any:
            return or_(*(
                or_(c.like(f"-:{job}%"), and_(c.like(f"{job}%"), not_(c.like("%:%")))) for job in jobs
            ))

        deleted += await _delete_where(db, present, legacy)
    return deleted


async def purge_unscoped_checkpoints(db: Any, *, dry_run: bool) -> int:
    """Retention: delete every thread whose id does not start with an organisation, whatever its age. Postgres only.

    Since 2026-11-27 no such row can be written (`thread_key` refuses a run without an organisation); any that exist
    are older orphans that no organisation's erasure would match. Returns threads."""
    from sqlalchemy import text

    if db.bind is None or db.bind.dialect.name != "postgresql":
        return 0
    present = await _present(db)
    if "checkpoints" not in present:
        return 0
    ids = [
        r[0]
        for r in (
            await db.execute(
                text("SELECT DISTINCT thread_id FROM checkpoints WHERE thread_id !~ :ns"), {"ns": NAMESPACED_RE}
            )
        ).all()
    ]
    if not dry_run:
        for name in CHECKPOINT_DATA_TABLES:
            if name in present:
                await db.execute(text(f"DELETE FROM {name} WHERE thread_id !~ :ns"), {"ns": NAMESPACED_RE})
    return len(ids)


async def purge_old_checkpoints(db: Any, *, days: int, dry_run: bool, now: Any) -> int:
    """Retention: delete the threads whose newest checkpoint is older than `days`. Postgres only; returns threads.

    No production code reads a checkpoint back: every run has its own thread (`thread_key`) and nothing resumes one,
    so the rows have no consumer; they are kept only `RETENTION_CHECKPOINT_DAYS` (default 3) as a short window in
    which an operator could look at a crashed run by hand (no tool does today). The age is the checkpoint's own `ts`
    (the library keeps no column for it)."""
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
