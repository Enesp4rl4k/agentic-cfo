"""Stuck-job reaper — every claim must have an expiry (DDIA Ch.1).

Three ways a run dies without reaching a terminal state:

  1. The worker process is killed mid-analysis. The claim stays `analyzing`
     and nothing will ever move it — a lease with no reaper is a column, not
     a lease. Past `lease_expires_at` the job is failed so it can be re-run.
  2. The job reached the broker but no worker ever claimed it (queue lost,
     worker never started). It was stamped with an enqueue lease at dispatch;
     past `stale_pending_minutes` it is failed with a message that says so.
     A job nobody enqueued (manual-trigger flow) has no lease and is never
     touched.
  3. The LangGraph run ledger keeps `agent_runs` rows `running`; a crash
     between flush and terminal commit leaves them running forever, which
     poisons `/runs/slo`. Past `stale_agent_run_minutes` they are failed.

`awaiting_review` is deliberately never reaped: a human holding the gate is
not a fault, and failing it would throw away a finished analysis.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def reap_stuck_jobs(db: AsyncSession) -> dict[str, Any]:
    """Fail every non-terminal row past its lease. Commits; returns counts."""
    from app.config import get_settings
    from app.models.agent_run import AgentRun
    from app.models.analysis_job import AnalysisJob, JobStatus

    settings = get_settings()
    now = datetime.now(UTC)

    # 1. Expired leases on active work (dead worker).
    expired = await db.execute(
        update(AnalysisJob)
        .where(
            AnalysisJob.status.in_((
                JobStatus.INGESTING.value,
                JobStatus.ANALYZING.value,
            )),
            AnalysisJob.lease_expires_at.is_not(None),
            AnalysisJob.lease_expires_at < now,
        )
        .values(
            status=JobStatus.FAILED.value,
            error_message=(
                "Analysis lease expired — the worker running this job stopped "
                "without finishing. Re-run the analysis."
            ),
            lease_expires_at=None,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )

    # 2. Enqueued but never claimed (no worker ever saw it).
    stale_pending = await db.execute(
        update(AnalysisJob)
        .where(
            AnalysisJob.status == JobStatus.PENDING.value,
            AnalysisJob.locked_by == "enqueue",
            AnalysisJob.lease_expires_at.is_not(None),
            AnalysisJob.lease_expires_at < now,
        )
        .values(
            status=JobStatus.FAILED.value,
            error_message=(
                "The job was queued but no worker picked it up "
                f"within {settings.stale_pending_minutes} minutes. "
                "Check the worker deployment, then re-run."
            ),
            lease_expires_at=None,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )

    # 3. Ledger rows left `running` by a crash between flush and commit.
    stale_runs = await db.execute(
        update(AgentRun)
        .where(
            AgentRun.status == "running",
            AgentRun.updated_at < now
            - timedelta(minutes=settings.stale_agent_run_minutes),
        )
        .values(
            status="failed",
            error="Run ledger lease expired — the process executing this run "
            "stopped without recording a terminal state.",
            finished_at=now,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )

    await db.commit()

    counts = {
        "expired_leases": int(expired.rowcount or 0),
        "stale_pending": int(stale_pending.rowcount or 0),
        "stale_runs": int(stale_runs.rowcount or 0),
    }
    total = sum(counts.values())
    if total:
        logger.warning("Stuck-job reaper: %s", counts)
    else:
        logger.debug("Stuck-job reaper: nothing to reap")
    return counts


async def reap_and_notify() -> dict[str, Any]:
    """Reaper entrypoint for the scheduler: own session, best-effort SSE note
    so a browser still watching a reaped job stops waiting."""
    from app.database import engine, get_session_factory

    async with get_session_factory(engine())() as db:
        counts = await reap_stuck_jobs(db)

    if counts.get("expired_leases") or counts.get("stale_pending"):
        try:
            from app.streaming.sse import publish_job_error

            await publish_job_error(
                "_reaper",
                "Analysis stopped — the worker running it is gone. Re-run it.",
            )
        except Exception:  # pragma: no cover - best-effort notification
            pass
    return counts
