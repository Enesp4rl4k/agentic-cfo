"""Atomic job state transitions — the claim is the idempotency mechanism.

Design (DDIA Ch.7 "Concurrency", Ch.11 "idempotent operations"):
  - The *database* is the single source of truth for who runs a job. A
    check-then-enqueue in the API cannot stop a double-click: both requests
    pass the read before either writes. So duplicates are allowed to be
    enqueued, and the **worker claim** — one atomic
    `UPDATE ... SET status='analyzing' WHERE status IN ('pending','failed')`
    whose rowcount decides — runs exactly once. The second delivery sees
    rowcount 0 and exits without writing a row.
  - Terminal transitions guard the same way: outputs and status commit in one
    transaction, and only a worker that still holds the claim can write them
    (`WHERE status IN ('analyzing','ingesting')`). If a reaper already failed
    the job, the rowcount is 0 and the caller rolls back instead of writing
    results into a job the platform has declared dead.
  - The lease (`lease_expires_at`) exists for the reaper, not for the claim:
    a crashed worker cannot release anything, so the claim must expire on a
    clock instead of on a liveness signal we do not have.

Nothing in this module commits except `claim_for_analysis` (a claim with no
transaction of its own would not exist for the next claimer to see).
`finish_job` / `fail_job` deliberately do NOT commit: outputs and status must
land in the caller's transaction.
"""
from __future__ import annotations

import os
import socket
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analysis_job import AnalysisJob, JobStatus

# Identifies *this process* for lease diagnostics ("which worker held it?").
WORKER_ID = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"

_ACTIVE_STATUSES = (JobStatus.INGESTING.value, JobStatus.ANALYZING.value)
_CLAIMABLE_STATUSES = (JobStatus.PENDING.value, JobStatus.FAILED.value)


async def claim_for_analysis(
    db: AsyncSession,
    job_id: str,
    *,
    worker_id: str | None = None,
    lease_seconds: int | None = None,
) -> AnalysisJob | None:
    """Atomically take a pending/failed job for analysis.

    Returns the claimed row, or None when someone else already holds it (or
    the job does not exist). The UPDATE and its commit are the claim — there
    is no window between "checked" and "claimed".
    """
    from app.config import get_settings

    if lease_seconds is None:
        lease_seconds = get_settings().job_lease_seconds
    now = datetime.now(UTC)
    stmt = (
        update(AnalysisJob)
        .where(
            AnalysisJob.id == job_id,
            AnalysisJob.status.in_(_CLAIMABLE_STATUSES),
        )
        .values(
            status=JobStatus.ANALYZING.value,
            locked_by=worker_id or WORKER_ID,
            locked_at=now,
            lease_expires_at=now + timedelta(seconds=lease_seconds),
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    result = await db.execute(stmt)
    await db.commit()
    if result.rowcount != 1:
        return None
    return await db.get(AnalysisJob, job_id)


async def mark_enqueue_lease(db: AsyncSession, job_id: str) -> bool:
    """Stamp a pending job as handed to the broker (best-effort).

    Gives the reaper something to expire: without a lease, a job that was
    enqueued but never picked up (worker down, queue lost) stays `pending`
    forever and the user waits on a run that will never come. Jobs nobody
    enqueued — the manual-trigger flow with auto-enqueue off — carry no lease
    and are deliberately never reaped.
    """
    from app.config import get_settings

    now = datetime.now(UTC)
    minutes = get_settings().stale_pending_minutes
    stmt = (
        update(AnalysisJob)
        .where(
            AnalysisJob.id == job_id,
            AnalysisJob.status == JobStatus.PENDING.value,
            AnalysisJob.locked_by.is_(None),
        )
        .values(
            locked_by="enqueue",
            locked_at=now,
            lease_expires_at=now + timedelta(minutes=minutes),
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount == 1


async def finish_job(
    db: AsyncSession,
    job_id: str,
    *,
    status: JobStatus,
    values: dict[str, Any] | None = None,
) -> bool:
    """Atomically close an active job with its results.

    Does not commit — the caller adds outputs to the same session so results
    and status are one transaction: either a job has both or neither.
    """
    now = datetime.now(UTC)
    payload: dict[str, Any] = dict(values or {})
    payload.update(
        status=status.value,
        lease_expires_at=None,
        updated_at=now,
    )
    stmt = (
        update(AnalysisJob)
        .where(AnalysisJob.id == job_id, AnalysisJob.status.in_(_ACTIVE_STATUSES))
        .values(**payload)
        .execution_options(synchronize_session=False)
    )
    result = await db.execute(stmt)
    return result.rowcount == 1


async def fail_job(
    db: AsyncSession,
    job_id: str,
    *,
    error: str,
    values: dict[str, Any] | None = None,
) -> bool:
    """Atomically close an active job with a failure. Does not commit
    (see `finish_job`)."""
    now = datetime.now(UTC)
    payload: dict[str, Any] = dict(values or {})
    payload.update(
        status=JobStatus.FAILED.value,
        error_message=error,
        lease_expires_at=None,
        updated_at=now,
    )
    stmt = (
        update(AnalysisJob)
        .where(AnalysisJob.id == job_id, AnalysisJob.status.in_(_ACTIVE_STATUSES))
        .values(**payload)
        .execution_options(synchronize_session=False)
    )
    result = await db.execute(stmt)
    return result.rowcount == 1


async def purge_job_outputs(db: AsyncSession, job_id: str) -> None:
    """Delete everything a previous attempt persisted for this job.

    Makes a re-run an idempotent recompute (DDIA Ch.11): the pipeline is
    allowed to run twice for one job, but the tables must end up holding the
    outputs of the last run — not a union of two. The caller commits, so the
    purge and the new rows are atomic.
    """
    from app.models.anomaly import Anomaly
    from app.models.report import Report
    from app.models.transaction import Transaction

    for model in (Transaction, Report, Anomaly):
        await db.execute(
            delete(model).where(model.job_id == job_id).execution_options(
                synchronize_session=False
            )
        )
