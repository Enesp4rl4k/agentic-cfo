"""P4-3 event sources — the seam that feeds real events into the trigger engine.

``handle_event`` (P4-1) evaluates rules against events; this module emits those
events from where they actually happen:

    job.completed   — a CFO analysis finished (the worker run, or the review
                      approval that released it — both ride
                      ``continue_after_completion``)
    tx.arrived      — parsed transactions landed for that job
    anomaly.detected — a detection pass persisted anomalies for a job (the
                      analysis itself, the daily rescan, or a manual rescan)
    schedule        — once per UTC day, for every org with a schedule rule
                      (an hourly scheduler tick; the day keys idempotency)

Every ``EventKind`` has an emitter here — ``test_trigger_sources`` pins that
parity, so a kind added to the contract without a source fails CI instead of
letting users build rules that can never fire.

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

import hashlib
import json
import logging
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.trigger import TriggerDefinitionRow
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


def _severity(value: Any) -> str:
    return str(getattr(value, "value", value) or "unknown")


async def emit_anomaly_detected(
    db: AsyncSession,
    *,
    job_id: str,
    org_id: str,
) -> list[TriggerRunOutcome]:
    """``anomaly.detected`` — the job's persisted anomalies, as one event.

    Reads the ``anomalies`` rows rather than a caller's in-memory list, so the
    analysis, the daily rescan and a manual rescan all emit the same thing.
    ``event_ref`` fingerprints the findings (type, severity, title): a rescan
    that finds the same anomalies is a duplicate, a rescan that finds new ones
    is a new event. No anomalies → no event. ``values`` stays ``None`` (latest
    semantic snapshot, as for ``tx.arrived``); the counts ride the payload.
    """
    from app.models.anomaly import Anomaly

    rows = (
        await db.execute(select(Anomaly).where(Anomaly.job_id == job_id))
    ).scalars().all()
    if not rows:
        logger.debug("anomaly.detected skipped: job=%s has no anomalies", job_id)
        return []

    findings = sorted(
        (str(r.anomaly_type), _severity(r.severity), str(r.title)) for r in rows
    )
    digest = hashlib.sha256(
        json.dumps(findings, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:16]
    by_severity = Counter(sev for _, sev, _ in findings)
    return await handle_event(
        db,
        org_id=org_id,
        event_kind="anomaly.detected",
        event_ref=f"anomaly:{job_id}:{digest}",
        payload={
            "job_id": job_id,
            "anomaly_count": len(findings),
            "by_severity": dict(by_severity),
        },
    )


async def emit_schedule_tick(
    db: AsyncSession,
    *,
    now: datetime | None = None,
) -> list[TriggerRunOutcome]:
    """``schedule`` — evaluate every org's schedule rules once per UTC day.

    The scheduler calls this hourly; ``event_ref`` is the UTC date, so the
    first tick of a day fires and the rest are duplicates — a server that was
    down at midnight still evaluates that day on its next tick. One org's
    failure is logged and skipped, never another org's evaluation.
    """
    day = (now or datetime.now(UTC)).astimezone(UTC).date().isoformat()
    rows = (
        await db.execute(
            select(TriggerDefinitionRow.org_id, TriggerDefinitionRow.events).where(
                TriggerDefinitionRow.enabled.is_(True)
            )
        )
    ).all()
    org_ids = sorted({org for org, events in rows if "schedule" in json.loads(events)})

    outcomes: list[TriggerRunOutcome] = []
    for org_id in org_ids:
        try:
            outcomes += await handle_event(
                db,
                org_id=org_id,
                event_kind="schedule",
                event_ref=f"schedule:{day}",
                payload={"date": day},
            )
        except Exception as exc:
            await db.rollback()
            logger.warning("schedule tick failed for org=%s: %s", org_id, exc)
    return outcomes


async def emit_job_events(
    db: AsyncSession,
    *,
    job_id: str,
    org_id: str,
    dashboard: dict[str, Any] | None,
) -> list[TriggerRunOutcome]:
    """The completion events, in one session — the call site's single seam."""
    outcomes = await emit_job_completed(
        db, job_id=job_id, org_id=org_id, dashboard=dashboard
    )
    outcomes += await emit_tx_arrived(db, job_id=job_id, org_id=org_id)
    return outcomes + await emit_anomaly_detected(db, job_id=job_id, org_id=org_id)
