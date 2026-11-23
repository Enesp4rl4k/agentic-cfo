"""The ledger of scheduled runs: one row per (job, organisation, period), claimed before work, finished with it.

Why a ledger. A cron tick is a moment; a missed moment is gone (the scheduler keeps no jobs across a
restart), and two processes can both fire it. What must be true is "this period's run for this company
happened exactly once", and that is a fact to store, not a schedule to trust:

* `claim` inserts the row. The unique key decides the winner of two simultaneous claims; the loser gets
  None and does nothing. A `done` row is never claimed again. A `failed` row is claimed again until
  `MAX_ATTEMPTS`. A `running` row older than `LEASE` belongs to a process that died and is taken over.
* the work and `mark_done` are written in ONE transaction by the runner (`schedule_runner.run_guarded`):
  a crash before the commit leaves nothing but the `running` claim, which expires; a crash after leaves a
  finished run. There is no state in which the work happened and the ledger does not say so.
* external effects inside the work (e-mail) go through the outbox, whose unique key makes a repeated
  write a no-op: a retry cannot send twice even if the work is repeated.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import and_, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job_run import DONE, FAILED, RUNNING, ScheduledJobRun

LEASE = timedelta(minutes=20)
MAX_ATTEMPTS = 5


def _now() -> datetime:
    return datetime.now(UTC)


async def claim(
    db: AsyncSession, job: str, org_id: str, period: str, *, lease: timedelta = LEASE, now: datetime | None = None
) -> ScheduledJobRun | None:
    """Take the run for (job, org, period), or None when it is done, running elsewhere, or out of attempts.

    Commits (the claim must be visible to the other process before the work starts)."""
    moment = now or _now()
    row = ScheduledJobRun(job=job, org_id=org_id, period=period, status=RUNNING, attempts=1, claimed_at=moment)
    try:
        async with db.begin_nested():
            db.add(row)
            await db.flush()
        await db.commit()
        return row
    except IntegrityError:
        pass
    taken = cast(
        CursorResult[Any],
        await db.execute(
        update(ScheduledJobRun)
        .where(
            ScheduledJobRun.job == job,
            ScheduledJobRun.org_id == org_id,
            ScheduledJobRun.period == period,
            or_(
                and_(ScheduledJobRun.status == FAILED, ScheduledJobRun.attempts < MAX_ATTEMPTS),
                and_(ScheduledJobRun.status == RUNNING, ScheduledJobRun.claimed_at < moment - lease),
            ),
        )
        .values(status=RUNNING, attempts=ScheduledJobRun.attempts + 1, claimed_at=moment, last_error=None)
        .execution_options(synchronize_session=False)
        ),
    )
    await db.commit()
    if taken.rowcount != 1:
        return None
    return (
        await db.execute(
            select(ScheduledJobRun).where(
                ScheduledJobRun.job == job, ScheduledJobRun.org_id == org_id, ScheduledJobRun.period == period
            )
        )
    ).scalar_one()


async def mark_done(db: AsyncSession, run_id: str, *, now: datetime | None = None) -> None:
    """Finish the run in the caller's transaction (the caller commits, together with the work)."""
    await db.execute(
        update(ScheduledJobRun)
        .where(ScheduledJobRun.id == run_id)
        .values(status=DONE, finished_at=now or _now(), last_error=None)
        .execution_options(synchronize_session=False)
    )


async def mark_failed(db: AsyncSession, run_id: str, error: str) -> int:
    """Record the failure (own transaction) and return how many attempts this period has had."""
    await db.execute(
        update(ScheduledJobRun)
        .where(ScheduledJobRun.id == run_id)
        .values(status=FAILED, finished_at=_now(), last_error=error[:300])
        .execution_options(synchronize_session=False)
    )
    await db.commit()
    attempts = (
        await db.execute(select(ScheduledJobRun.attempts).where(ScheduledJobRun.id == run_id))
    ).scalar_one()
    return int(attempts)


async def is_done(db: AsyncSession, job: str, org_id: str, period: str) -> bool:
    status = (
        await db.execute(
            select(ScheduledJobRun.status).where(
                ScheduledJobRun.job == job, ScheduledJobRun.org_id == org_id, ScheduledJobRun.period == period
            )
        )
    ).scalar_one_or_none()
    return status == DONE
