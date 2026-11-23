"""Run a scheduled unit of work once per (job, organisation, period); catch it up when the schedule was missed.

`run_guarded` is the only way the scheduler's per-company jobs run: claim the ledger row, do the work and
finish the row in one transaction, record a failure and alert the operators when it keeps failing.
`catch_up` is the answer to "the worker restarted at 07:00": the scheduler keeps no jobs across a restart,
so on start (and every ten minutes after) each job asks whether its latest due run is inside its window and
not finished, and runs it. A run that already happened is a cheap no-op, so the ordinary cron tick, the
catch-up and a second scheduler can all call the same function.

Windows decide what is worth running late. A briefing is still useful the same morning; an hourly scan
from three hours ago is not (the next one is due), so it is skipped, never queued up.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

GLOBAL = "*"
# A run this long after its due time is a catch-up, not the ordinary cron tick (which fires within seconds).
CATCH_UP_AFTER = timedelta(minutes=5)


@dataclass
class RunReport:
    done: int = 0
    skipped: int = 0
    failed: int = 0
    orgs_done: list[str] = field(default_factory=list)

    def merge(self, other: RunReport) -> None:
        self.done += other.done
        self.skipped += other.skipped
        self.failed += other.failed
        self.orgs_done += other.orgs_done


async def run_guarded(
    job: str,
    org_id: str,
    period: str,
    work: Callable[[AsyncSession], Awaitable[None]],
    report: RunReport | None = None,
) -> str:
    """Do `work` for (job, org, period) at most once successfully. Returns done | skipped | failed.

    `work` gets a session and must leave the commit to this function: its writes and the ledger's
    `done` land together or not at all."""
    from app.config import get_settings
    from app.database import engine, get_session_factory
    from app.services import job_runs
    from app.services.operator_alerts import alert_in_own_session

    report = report if report is not None else RunReport()
    factory = get_session_factory(engine())
    async with factory() as db:
        run = await job_runs.claim(db, job, org_id, period)
        run_id = None if run is None else str(run.id)
    if run_id is None:
        report.skipped += 1
        return "skipped"
    try:
        async with factory() as db:
            await work(db)
            await job_runs.mark_done(db, run_id)
            await db.commit()
    except Exception as exc:
        logger.exception("scheduled job %s failed (org=%s period=%s)", job, org_id, period)
        async with factory() as db:
            attempts = await job_runs.mark_failed(db, run_id, f"{type(exc).__name__}: {exc}")
        report.failed += 1
        if attempts >= get_settings().job_failure_alert_after:
            await alert_in_own_session(
                "job_failed", dedupe=f"{job}:{org_id}:{period}",
                detail=f"iş={job} dönem={period} org={org_id} deneme={attempts} hata={type(exc).__name__}",
            )
        return "failed"
    report.done += 1
    if org_id != GLOBAL:
        report.orgs_done.append(org_id)
    return "done"


# ── Due times ────────────────────────────────────────────────────────────────


def latest_daily(now: datetime, hour: int, minute: int = 0) -> datetime:
    due = now.astimezone(UTC).replace(hour=hour, minute=minute, second=0, microsecond=0)
    return due if due <= now else due - timedelta(days=1)


def latest_weekly(now: datetime, weekday: int, hour: int, minute: int = 0) -> datetime:
    """The latest `weekday` (Monday = 0) at hour:minute UTC that is not after `now`."""
    due = latest_daily(now, hour, minute)
    return due - timedelta(days=(due.weekday() - weekday) % 7)


def latest_hourly(now: datetime, minute: int) -> datetime:
    due = now.astimezone(UTC).replace(minute=minute, second=0, microsecond=0)
    return due if due <= now else due - timedelta(hours=1)


MONDAY_BRIEFING = "monday_briefing"
MORNING_BRIEF = "morning_brief"
NIGHTLY_INTELLIGENCE = "nightly_intelligence"
HOURLY_KRI_SCAN = "hourly_kri_scan"


@dataclass(frozen=True)
class Spec:
    job: str
    due: Callable[[datetime], datetime]
    window: timedelta
    period: Callable[[datetime], str]
    alert_when_late: bool = False


def _day(due: datetime) -> str:
    return due.date().isoformat()


SPECS: dict[str, Spec] = {
    # The Monday briefing (and the weekly anomaly summary with it): useful all of Monday.
    MONDAY_BRIEFING: Spec(MONDAY_BRIEFING, lambda n: latest_weekly(n, 0, 7), timedelta(hours=17), _day, True),
    MORNING_BRIEF: Spec(MORNING_BRIEF, lambda n: latest_daily(n, 7), timedelta(hours=17), _day),
    # Due 02:00; still worth running through the morning, not after midday.
    NIGHTLY_INTELLIGENCE: Spec(NIGHTLY_INTELLIGENCE, lambda n: latest_daily(n, 2), timedelta(hours=10), _day),
    # Hourly at :15; late means "within this hour". An older scan is skipped: the next one is due.
    HOURLY_KRI_SCAN: Spec(
        HOURLY_KRI_SCAN, lambda n: latest_hourly(n, 15), timedelta(minutes=45),
        lambda due: due.strftime("%Y-%m-%dT%H"),
    ),
}


def period_for(job: str, now: datetime | None = None) -> str:
    """The period key a run of `job` made now belongs to (the same for the cron tick and the catch-up)."""
    moment = now or datetime.now(UTC)
    spec = SPECS[job]
    return spec.period(spec.due(moment))


async def catch_up(now: datetime | None = None) -> dict[str, RunReport]:
    """Run what was due, is inside its window and has not finished. Safe to call as often as you like."""
    from app import scheduler
    from app.services.operator_alerts import alert_in_own_session

    moment = now or datetime.now(UTC)
    runners: dict[str, Callable[..., Awaitable[RunReport]]] = {
        MONDAY_BRIEFING: scheduler._dispatch_monday_briefings,
        MORNING_BRIEF: scheduler._generate_morning_brief,
        NIGHTLY_INTELLIGENCE: scheduler._nightly_intelligence_run,
        HOURLY_KRI_SCAN: scheduler._hourly_proactive_kri_scan,
    }
    reports: dict[str, RunReport] = {}
    for job, spec in SPECS.items():
        due = spec.due(moment)
        late = moment - due
        if late > spec.window:
            logger.info("catch-up: %s due %s is stale (%s late), skipped", job, due.isoformat(), late)
            continue
        try:
            report = await runners[job](now=moment)
        except Exception:
            logger.exception("catch-up of %s failed", job)
            continue
        reports[job] = report
        if report.done and late > CATCH_UP_AFTER:
            logger.warning(
                "catch-up: %s ran %d missed run(s) for %s (%s after its due time)", job, report.done,
                spec.period(due), late,
            )
            if spec.alert_when_late:
                await alert_in_own_session(
                    "briefing_caught_up", dedupe=f"{job}:{spec.period(due)}",
                    detail=(
                        f"iş={job} dönem={spec.period(due)} telafi={report.done} "
                        f"gecikme={int(late.total_seconds() // 60)}dk"
                    ),
                )
    return reports
