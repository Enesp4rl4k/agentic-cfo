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

How it is applied (`refuse_if_erased`), and why it is airtight on PostgreSQL: the writer takes the organisation's
advisory lock in SHARED mode inside its own transaction, then reads the tombstone. The erase transaction takes the
same lock EXCLUSIVELY as its first statement (`org_erasure._lock_org`). So either the writer saw no tombstone and
holds the shared lock until its commit (the erasure waits for it and then deletes what it wrote), or it waits for the
erasure and then sees the proof record and refuses. There is no third order. SQLite (development) has one writer at a
time and no advisory locks: the check alone.

Where it is applied:

* EVERY database write of an organisation-scoped table, by the session itself (`privacy.write_guard`: the ORM flush
  and every Core INSERT / UPDATE), so no write path has to remember it; the analysis paths also call
  `refuse_if_erased` explicitly as the first statement of their transactions;
* Redis writes of company data (`redis_write_allowed`, a check right before the write: Redis has no transaction);
  `tests/test_write_guard.py` fails on a Redis write site that neither checks nor is exempt with a reason;
* writers on connections of their own: the LangGraph saver checks without the lock; the agent memory insert carries
  the predicate and takes the lock itself; the model-call log (platform layer, may not import this) does not check.

What gets past (a write that cannot be resolved to its organisation, the model-call log, a Redis write racing the
check) is removed by the final sweep at the end of the erasure and by every retention run (`sweep_erased_org`): the
erasure's own plan run again, every org-scoped table, checkpoints, agent memory, files and Redis keys, not gated by
RETENTION_DRY_RUN.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
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
    if db.get_bind().dialect.name == "postgresql":  # the session-wide guard need not read it again (write_guard)
        db.info.setdefault("tombstone_checked", set()).add(str(org_id))


async def org_erased_now(org_id: str | None) -> bool:
    """`is_erased` in a session of its own, for a best-effort writer that holds none (a CEO result in Redis with its
    own time-to-live). A database that cannot answer is logged and read as "not erased": these
    writes are covered after the erasure anyway (the Redis result by its 24-hour time-to-live)."""
    if not org_id:
        return False
    from app.database import engine, get_session_factory

    try:
        async with get_session_factory(engine())() as db:
            return await is_erased(db, str(org_id))
    except Exception as exc:
        logger.warning("erasure tombstone unreadable (%s): write allowed, the final sweep covers it", type(exc).__name__)
        return False


_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
# Per process: an organisation found erased stays erased (cached for good); one found live is asked again after
# NEGATIVE_TTL seconds. A Redis write in that window is removed by the final sweep / retention (keys naming the org).
NEGATIVE_TTL = 5.0
_ERASED_SEEN: set[str] = set()
_LIVE_SEEN: dict[str, float] = {}


async def redis_write_allowed(*names: str | None) -> bool:
    """Before a Redis write of company data: False when an organisation named by `names` (an organisation id, or a
    key that contains one) is being erased or was erased. Redis has no transaction to lock in, so this is a check
    immediately before the write; the erasure's Redis sweep, run again by the final sweep and every retention run,
    deletes any key that names the organisation. `tests/test_write_guard.py` requires every Redis write site to call
    this or to be listed as exempt with a reason."""
    import time

    candidates = {m for n in names if n for m in _UUID_RE.findall(str(n).lower())}
    now = time.monotonic()
    for org in candidates:
        if org in _ERASED_SEEN:
            return False
        if now - _LIVE_SEEN.get(org, -NEGATIVE_TTL - 1) < NEGATIVE_TTL:
            continue
        if await org_erased_now(org):
            _ERASED_SEEN.add(org)
            logger.warning("redis write refused: the organisation is being erased or was erased")
            return False
        _LIVE_SEEN[org] = now
    return True


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


async def sweep_erased_org(
    db: AsyncSession, org_id: str, *, mode: str = "anonymise", plan: dict[str, Any] | None = None,
    storage_root: Path | None = None,
) -> dict[str, int]:
    """The final sweep of an erased organisation: the ERASURE'S OWN PLAN run again, in a transaction of its own under
    the same per-organisation lock, then its cleanup (files, caches, Redis). Commits. Counts only.

    There is no second list of tables: `org_erasure._erase` derives the organisation's tables from the schema (a new
    org-scoped table the erasure does not place fails `tests/test_org_erasure.py`, so it cannot escape this either),
    deletes what is not retained, re-scrubs only rows not yet scrubbed (`_not_scrubbed`), and erases the checkpoints
    and the Postgres agent memory. `plan` is the erasure's stored cleanup plan: its user, job and export ids are gone
    from the tables now and are added to the cleanup so their Redis keys and files are looked for again. Run at the
    end of an erasure's cleanup (`erasure_flow.run_cleanup_step`) and by every retention run for organisations erased
    in the last `retention.ERASURE_SWEEP_DAYS` days, whatever RETENTION_DRY_RUN says. Idempotent."""
    from app.config import get_settings
    from app.services.org_erasure import _erase, _lock_org, hash_id
    from app.services.privacy.erasure_cleanup import require_ids, run_cleanup
    from app.services.privacy.write_guard import exempt

    require_ids(org_id)
    root = storage_root or Path(get_settings().storage_local_path)
    try:
        with exempt(db):
            await _lock_org(db, org_id)
            counts, again = await _erase(db, org_id, hash_id("org", org_id), mode, root)
            await db.commit()
    except BaseException:
        await db.rollback()
        raise
    for key in ("user_ids", "job_ids", "export_ids", "paths"):
        again[key] = list(dict.fromkeys([*(again.get(key) or []), *((plan or {}).get(key) or [])]))
    done = await run_cleanup(again, root)
    rows = sum(int(n) for table, kinds in counts.items() if not table.startswith("_") and isinstance(kinds, dict)
               for n in kinds.values())
    eph = {**(counts.get("_ephemeral") or {}), **(done.get("_ephemeral") or {})}
    return {"rows": rows, "checkpoints": int((counts.get("_ephemeral") or {}).get("checkpoints_deleted", 0)),
            "agent_memory": int((counts.get("_ephemeral") or {}).get("agent_memory_deleted", 0)),
            "files": int((done.get("_files") or {}).get("deleted", 0)), "redis": int(eph.get("redis_deleted", 0)),
            "redis_failed": int(eph.get("redis_failed", 0))}
