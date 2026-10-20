"""P4-3 event sources — the seam that feeds real events into the trigger engine.

``handle_event`` (P4-1) evaluates rules against events; this module emits those
events from where they actually happen:

    job.completed   — a CFO analysis finished (the worker run, or the review
                      approval that released it — both ride
                      ``continue_after_completion``)
    tx.arrived      — parsed transactions landed for that job

Values: ``job.completed`` carries the metrics projected from the very dashboard
the analysis persisted — the same projector the semantic snapshot uses, so a
condition written against catalog ids sees one consistent unit (lira→cents at
the same boundary). ``tx.arrived`` omits values on purpose: the engine then
loads the org's latest semantic snapshot, i.e. "the company as it stands now"
when the transactions landed.

``event_ref`` is the job id for both events, so the engine's
``(trigger, event_ref)`` uniqueness makes a worker-then-approval continuation
fire once, not twice — and an ARQ retry of a failed run can't double-fire.

Isolation contract: callers emit from their own session (the engine commits
its own audit rows), and the call site wraps emission in the same non-fatal
guard ``continue_after_completion`` uses for cache invalidation — a trigger
that misbehaves must never fail the analysis it rode in on.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.triggers.engine import TriggerRunOutcome, handle_event

logger = logging.getLogger(__name__)


def _metric_values(dashboard: dict[str, Any], job_id: str) -> dict[str, Any]:
    """``{metric_id: value}`` for the dashboard the analysis persisted."""
    from app.services.semantic.projectors import project_from_cfo

    points = project_from_cfo({"dashboard": dashboard}, job_id=job_id)
    return {
        p.metric_id: p.value
        for p in points
        if p.value is not None
    }


async def emit_job_completed(
    db: AsyncSession,
    *,
    job_id: str,
    org_id: str,
    dashboard: dict[str, Any] | None,
) -> list[TriggerRunOutcome]:
    """``job.completed`` — an analysis finished; conditions see its metrics.

    Returns the engine's outcomes (empty when no rule listens for the event).
    """
    return await handle_event(
        db,
        org_id=org_id,
        event_kind="job.completed",
        event_ref=job_id,
        values=_metric_values(dashboard or {}, job_id),
        payload={"job_id": job_id},
    )


async def emit_tx_arrived(
    db: AsyncSession,
    *,
    job_id: str,
    org_id: str,
) -> list[TriggerRunOutcome]:
    """``tx.arrived`` — parsed transactions landed for a job.

    Skipped when the job holds no transactions (a re-run that purged them, say)
    — "nothing arrived" is not an event. ``values`` stays ``None`` so the engine
    evaluates against the org's latest semantic snapshot.
    """
    from app.models.transaction import Transaction

    count = (
        await db.execute(
            select(func.count())
            .select_from(Transaction)
            .where(Transaction.job_id == job_id)
        )
    ).scalar() or 0
    if not count:
        logger.debug("tx.arrived skipped: job=%s has no transactions", job_id)
        return []
    return await handle_event(
        db,
        org_id=org_id,
        event_kind="tx.arrived",
        event_ref=job_id,
        payload={"job_id": job_id, "tx_count": int(count)},
    )


async def emit_job_events(
    db: AsyncSession,
    *,
    job_id: str,
    org_id: str,
    dashboard: dict[str, Any] | None,
) -> list[TriggerRunOutcome]:
    """Both completion events, in one session — the call site's single seam."""
    outcomes = await emit_job_completed(
        db, job_id=job_id, org_id=org_id, dashboard=dashboard
    )
    return outcomes + await emit_tx_arrived(db, job_id=job_id, org_id=org_id)
