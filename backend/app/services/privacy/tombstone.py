"""The erasure tombstone: an organisation being erased, or erased, accepts no new analysis state or result.

Why: a CFO / CEO run can take minutes. One that started before an organisation's erasure and finished after it
committed wrote its checkpoints, results, run ledger, model-call log and agent memory under the erased company,
where no erasure would ever look again.

What marks an organisation (no new table, no migration; both rows exist already and carry only hashes):

* an organisation erasure request for it (`scope = "org"`, matched by `org_hash`) that the executor has CLAIMED:
  `executing`, `cleanup_pending` or `executed`. The claim is committed before the erase transaction starts
  (`erasure_flow._claim`), so it is the tombstone from the first destructive moment on;
* a proof record of an organisation erasure (`org_erasure_records`, mode `anonymise` / `hard_delete`): an erasure run
  without a request (a restore re-application) is marked from its commit on.

A `failed` request is not a tombstone: its transaction rolled back whole, the company is intact and keeps working;
the retry erases whatever was written meanwhile. A cancelled one never touched anything.

How a write path uses it (`refuse_if_erased`), and why it is airtight on PostgreSQL: the writer takes the
organisation's advisory lock in SHARED mode inside its own transaction, then reads the tombstone. The erase
transaction takes the same lock EXCLUSIVELY as its first statement (`org_erasure._lock_org`). So either the writer
saw no tombstone and holds the shared lock until its commit (the erasure waits for it and then deletes what it
wrote), or it waits for the erasure and then sees the proof record and refuses. There is no third order. SQLite
(development) has one writer at a time and no advisory locks: the check alone.

Writers that are not on our session (the LangGraph saver's own pool, the agent memory's asyncpg pool, the model-call
log's own session) read the tombstone without the lock; what can slip through that window is removed by the final
sweep at the end of the erasure (`org_erasure.sweep_erased_org`) and again by every retention run
(`retention.sweep_erasure_leftovers`), neither gated by RETENTION_DRY_RUN.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# The request statuses from the executor's claim on: the company's rows are being, or have been, deleted.
ERASING_STATUSES = ("executing", "cleanup_pending", "executed")
ORG_MODES = ("anonymise", "hard_delete")


class OrgErasedError(RuntimeError):
    """The organisation is being erased or was erased: nothing of an analysis run may be persisted for it.

    The message is fixed (no id, no data): it reaches logs and the run ledger's caller."""

    def __init__(self) -> None:
        super().__init__("organisation erased: nothing persisted")


def org_hash(org_id: str) -> str:
    from app.services.org_erasure import hash_id

    return hash_id("org", org_id)


def tombstone_clause(hashed: str) -> Any:
    """SQL: true when the organisation with this hash is being erased or was erased."""
    from app.models.erasure_record import OrgErasureRecord, OrgErasureRequest

    return or_(
        exists().where(OrgErasureRecord.org_hash == hashed, OrgErasureRecord.mode.in_(ORG_MODES)),
        exists().where(
            OrgErasureRequest.org_hash == hashed, OrgErasureRequest.scope == "org",
            OrgErasureRequest.status.in_(ERASING_STATUSES),
        ),
    )


async def is_erased(db: AsyncSession, org_id: str | None) -> bool:
    """Whether `org_id` is being erased or was (no lock). A run without an organisation is never erased."""
    if not org_id:
        return False
    with db.no_autoflush:  # read the tombstone BEFORE any pending write of the caller reaches the database
        return bool((await db.execute(select(tombstone_clause(org_hash(str(org_id)))))).scalar())


async def refuse_if_erased(db: AsyncSession, org_id: str | None) -> None:
    """Call inside the transaction that writes an analysis's state or results, before its first write.

    PostgreSQL: takes the organisation's advisory lock SHARED (released at the end of the caller's transaction), then
    reads the tombstone; raises `OrgErasedError` when it is set. Many writers of one company run side by side; only
    its erasure waits for them (see the module docstring)."""
    if not org_id:
        return
    if db.get_bind().dialect.name == "postgresql":
        from app.services.org_erasure import org_lock_key

        # No autoflush: the lock comes before any pending write (a write flushed first could hold a row lock the
        # erasure needs while this waits for the erasure's advisory lock).
        with db.no_autoflush:
            await db.execute(select(func.pg_advisory_xact_lock_shared(org_lock_key(str(org_id)))))
    if await is_erased(db, org_id):
        logger.warning("write refused: the organisation is being erased or was erased")
        raise OrgErasedError()


async def org_erased_now(org_id: str | None) -> bool:
    """`is_erased` in a session of its own, for a best-effort writer that holds none (a CEO result in Redis with its
    own time-to-live, a model-call log row). A database that cannot answer is logged and read as "not erased": these
    writes are swept after the erasure anyway (Redis by the cleanup plan, rows by `sweep_erased_org`)."""
    if not org_id:
        return False
    from app.database import engine, get_session_factory

    try:
        async with get_session_factory(engine())() as db:
            return await is_erased(db, str(org_id))
    except Exception as exc:
        logger.warning("erasure tombstone unreadable (%s): write allowed, the final sweep covers it", type(exc).__name__)
        return False


def org_of_thread(thread_id: str) -> str | None:
    """The organisation of a checkpoint thread (`<org_id>:<job_id>:<run_id>`), or None for a thread without one."""
    from app.services.privacy.erasure_cleanup import valid_id

    head = str(thread_id).split(":", 1)[0]
    return head if valid_id(head) else None


TOMBSTONE_SQL = (
    "SELECT EXISTS (SELECT 1 FROM org_erasure_records WHERE org_hash = %(h)s AND mode IN ('anonymise', 'hard_delete')) "
    "OR EXISTS (SELECT 1 FROM org_erasure_requests WHERE org_hash = %(h)s AND scope = 'org' "
    "AND status IN ('executing', 'cleanup_pending', 'executed')) AS erased"
)
"""The same predicate as `tombstone_clause`, for the LangGraph saver's psycopg connection (no SQLAlchemy there).
`tests/test_erasure_tombstone.py` keeps the two in step."""


def thread_refused(pool: Any, thread_id: str) -> bool:
    """For the Postgres checkpoint saver (sync, its own psycopg pool): True when the thread's organisation is being
    erased or was. A connection is borrowed for one SELECT and given back before the saver takes its own."""
    org = org_of_thread(thread_id)
    if org is None:
        return False
    with pool.connection() as conn:
        row = conn.execute(TOMBSTONE_SQL, {"h": org_hash(org)}).fetchone()
    if row is None:
        return False
    value = row["erased"] if isinstance(row, dict) else row[0]
    return bool(value)
