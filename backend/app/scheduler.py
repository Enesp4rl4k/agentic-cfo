"""
CFO Scheduler — APScheduler ile periyodik görevler.

Görevler:
- Günlük: Son 7 gündeki tüm completed job'ları tara, anomali yoksa çalıştır
- Haftalık: Haftalık özet rapor üret (gelecek fazda e-posta ile gönderilecek)

FastAPI lifespan'ında başlatılır, uygulama kapanışında durdurulur.
"""
from __future__ import annotations

import functools
import logging
import socket
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.services.schedule_runner import (
    GLOBAL,
    HOURLY_KRI_SCAN,
    MONDAY_BRIEFING,
    MORNING_BRIEF,
    NIGHTLY_INTELLIGENCE,
    RunReport,
    period_for,
    run_guarded,
)

logger = logging.getLogger(__name__)

# Module-level scheduler singleton
_scheduler: AsyncIOScheduler | None = None


def _exclusive(
    fn: Callable[..., Awaitable[object]],
    name: str,
    ttl: int = 1800,
) -> Callable[..., Awaitable[None]]:
    """Run `fn` in at most one process (DDIA Ch.8/Ch.11 — coordinated
    processes need a broker, not a hope).

    APScheduler starts in *every* uvicorn worker, so without this each cron
    tick ran N times: the daily anomaly scan inserted duplicates, the ERP
    sync hit vendor APIs N-fold. A Redis NX lock elects one runner; the
    others skip. Without a broker (dev/tests) the job runs locally — the
    old single-process behaviour.

    The lock is deliberately NOT released on completion: TTL is the
    release. Two workers' cron ticks can fire seconds apart (startup
    jitter), and a short job finishing before its twin fires would let the
    twin re-run the same tick. Holding the key for `ttl` (< the schedule
    interval) covers the whole tick; a crashed runner only blocks the next
    one for the TTL, never the run after that.
    """
    from app.core.redis_client import get_redis, mark_unavailable

    @functools.wraps(fn)
    async def _run() -> None:
        client = await get_redis()
        if client is not None:
            try:
                acquired = bool(
                    await client.set(
                        f"scheduler:lock:{name}",
                        socket.gethostname(),
                        ex=ttl,
                        nx=True,
                    )
                )
            except Exception as exc:
                mark_unavailable(exc)
                acquired = True  # broker down → run locally, as it always did
            if not acquired:
                logger.debug(
                    "Scheduler job %s skipped — held by another process", name
                )
                return
        await fn()

    return _run


async def _run_stuck_job_reaper() -> None:
    """Every 10 minutes: fail jobs whose lease expired and ledger runs left
    `running` by a crash (services/job_reaper.py)."""
    try:
        from app.services.job_reaper import reap_and_notify

        await reap_and_notify()
    except Exception as exc:
        logger.error("Stuck-job reaper run error: %s", exc)


async def _scan_recent_jobs() -> None:
    """
    Günlük görev: Son 7 günde tamamlanan job'lar için anomali taraması.
    Zaten anomalisi olan job'lar tekrar taranmaz (idempotent).
    """
    from sqlalchemy import func, select

    from app.agents.anomaly_agent import (
        detect_duplicates,
        detect_expense_spikes,
        detect_negative_cashflow_streak,
        detect_round_numbers,
        detect_unusual_amounts,
        detect_vendor_concentration,
    )
    from app.config import get_settings
    from app.database import engine, get_session_factory
    from app.models.analysis_job import AnalysisJob, JobStatus
    from app.models.anomaly import Anomaly
    from app.models.report import Report, ReportFormat
    from app.models.transaction import Transaction

    get_settings()
    cutoff = datetime.now(UTC) - timedelta(days=7)

    async with get_session_factory(engine())() as db:
        # Find completed jobs in the last 7 days
        result = await db.execute(
            select(AnalysisJob).where(
                AnalysisJob.status == JobStatus.COMPLETED,
                AnalysisJob.completed_at >= cutoff,
            )
        )
        jobs = result.scalars().all()
        logger.info("Scheduler: scanning %d recent jobs for anomalies", len(jobs))

        for job in jobs:
            # Skip if already has anomalies from today
            count_result = await db.execute(
                select(func.count()).select_from(Anomaly).where(
                    Anomaly.job_id == job.id,
                    Anomaly.created_at >= datetime.now(UTC).replace(
                        hour=0, minute=0, second=0, microsecond=0
                    ),
                )
            )
            if (count_result.scalar() or 0) > 0:
                continue

            # Load transactions
            tx_result = await db.execute(
                select(Transaction).where(Transaction.job_id == job.id)
            )
            txs = tx_result.scalars().all()
            if not txs:
                continue

            tx_dicts = [
                {
                    "id": tx.id,
                    "amount_cents": tx.amount_kurus,
                    "type": tx.type,
                    "category": tx.category,
                    "description": tx.description,
                    "vendor": tx.vendor,
                    "transaction_date": tx.transaction_date.isoformat() if tx.transaction_date else None,
                }
                for tx in txs
            ]

            # Load cashflow from dashboard JSON
            report_result = await db.execute(
                select(Report).where(
                    Report.job_id == job.id,
                    Report.report_format == ReportFormat.JSON,
                )
            )
            report = report_result.scalars().first()
            cashflow = report.data.get("cashflow", {}) if report and report.data else {}

            # Run detection
            anomalies: list[dict] = []
            anomalies.extend(detect_duplicates(tx_dicts))
            anomalies.extend(detect_unusual_amounts(tx_dicts))
            anomalies.extend(detect_vendor_concentration(tx_dicts))
            anomalies.extend(detect_expense_spikes(tx_dicts))
            anomalies.extend(detect_round_numbers(tx_dicts))
            if cashflow:
                anomalies.extend(detect_negative_cashflow_streak(cashflow))

            if anomalies:
                for a in anomalies:
                    db.add(Anomaly(
                        job_id=job.id,
                        anomaly_type=a["anomaly_type"],
                        severity=a["severity"],
                        title=a["title"],
                        description=a["description"],
                        transaction_ids=a.get("transaction_ids"),
                        evidence=a.get("evidence"),
                        confidence=a.get("confidence"),
                    ))
                await db.commit()
                logger.info(
                    "Scheduler: job=%s — persisted %d anomalies", job.id, len(anomalies)
                )
                if job.org_id:
                    # P4: anomaly.detected — non-fatal, a trigger never fails the scan.
                    try:
                        from app.services.triggers.sources import emit_anomaly_detected

                        await emit_anomaly_detected(
                            db, job_id=str(job.id), org_id=str(job.org_id)
                        )
                    except Exception as exc:
                        await db.rollback()
                        logger.warning(
                            "Scheduler: anomaly trigger failed job=%s (non-fatal): %s",
                            job.id, exc,
                        )
            else:
                logger.debug("Scheduler: job=%s — no anomalies found", job.id)


def monday_briefing_key(org_id: str) -> str:
    """Redis key for one organisation's deterministic Monday morning briefing."""
    return f"monday_briefing:{org_id}"


async def _dispatch_monday_briefings(now: datetime | None = None) -> RunReport:
    """Plan v10 §O4: Monday Morning Briefing dispatch.

    Every Monday at 07:00 UTC, and again by `schedule_catch_up` when that moment was missed:
    1. Assembles deterministic 3-sentence briefing from radar facts.
    2. Stores in Redis cache with 7-day TTL.
    3. Emits InAppNotification to the organization.

    One run per (organisation, Monday): the ledger row (`services/job_runs.py`) is claimed first and
    finished in the same transaction as the notification and the outbox rows, so a restart, a second
    scheduler or a crash in the middle neither loses nor repeats a briefing. The e-mails also carry an
    outbox key per recipient and briefing, a second guard against a double send.
    """
    from sqlalchemy import select

    from app.database import engine, get_session_factory
    from app.models.organization import Organization
    from app.services.outbox import deliver_pending

    moment = now or datetime.now(UTC)
    period = period_for(MONDAY_BRIEFING, moment)
    report = RunReport()
    logger.info("Scheduler: Monday morning briefing dispatch for %s", period)
    async with get_session_factory(engine())() as db:
        org_ids = [str(o) for o in (await db.execute(select(Organization.id))).scalars().all()]
    for org_id in org_ids:
        await run_guarded(
            MONDAY_BRIEFING, org_id, period, functools.partial(_monday_briefing_for_org, org_id, moment.date()), report
        )
    if report.done:
        async with get_session_factory(engine())() as db:
            await deliver_pending(db)
            await db.commit()
    logger.info("Scheduler: Monday morning briefing dispatch completed (%s)", report)
    return report


async def _monday_briefing_for_org(org_id: str, anchor: Any, db: Any) -> None:
    import json

    from app.models.in_app_notification import InAppNotification
    from app.services.briefing_delivery import enqueue_briefing_emails
    from app.services.monday_briefing import assemble_monday_briefing

    briefing = await assemble_monday_briefing(db, org_id, anchor_date=anchor)
    if not briefing.has_data:
        return  # nothing known about this company: no briefing, no invented calm
    # E-mail goes through the outbox: once per recipient, held for an accountant.
    await enqueue_briefing_emails(db, org_id, briefing, anchor_date=anchor)
    db.add(
        InAppNotification(
            org_id=org_id, level="info", domain="cfo", source="monday_briefing",
            message=f"{briefing.sentence_radar} {briefing.sentence_action}",
            action="route", priority_score=0.8,
        )
    )
    # Redis cache: a convenience copy, best effort (the screen recomputes from the radar).
    try:
        from app.services.privacy.tombstone import redis_write_allowed
        from app.worker import get_arq_pool

        pool = await get_arq_pool()
        if await redis_write_allowed(org_id):
            await pool.set(monday_briefing_key(org_id), json.dumps(briefing.to_dict()), ex=7 * 86400)
    except Exception as exc:
        logger.debug("Could not cache monday briefing in Redis for org %s: %s", org_id, exc)


async def _deliver_outbox() -> None:
    """Plan v11 C9: send what is pending (retries, released messages); record each outcome."""
    from app.database import engine, get_session_factory
    from app.services.outbox import deliver_pending

    async with get_session_factory(engine())() as db:
        await deliver_pending(db)
        await db.commit()


async def _record_radar_forecasts() -> None:
    """Plan v10 O5: write today's radar for every company, so that in four weeks
    there is a forecast, made before the fact, to grade against the bank."""
    from app.database import engine, get_session_factory
    from app.services.radar_forecast_log import record_daily_forecasts

    async with get_session_factory(engine())() as db:
        written = await record_daily_forecasts(db, today=datetime.now(UTC).date())
        await db.commit()
    logger.info("Scheduler: radar forecast log wrote %d forecasts", written)


async def _weekly_summary() -> None:
    """
    Haftalık görev: Anomali özeti logla.
    Gelecek fazda: e-posta ile CFO'ya gönder.
    """
    # 1. Monday morning briefing dispatch
    try:
        await _dispatch_monday_briefings()
    except Exception as exc:
        logger.error("Error during Monday briefing dispatch: %s", exc)

    # 2. Anomaly summary
    from sqlalchemy import func, select

    from app.database import engine, get_session_factory
    from app.models.anomaly import Anomaly

    cutoff = datetime.now(UTC) - timedelta(days=7)

    async with get_session_factory(engine())() as db:
        result = await db.execute(
            select(Anomaly.severity, func.count().label("n")).where(
                Anomaly.created_at >= cutoff
            ).group_by(Anomaly.severity)
        )
        rows = result.all()
        summary = {row.severity: row.n for row in rows}
        logger.info(
            "Weekly anomaly summary (last 7 days): critical=%d high=%d medium=%d low=%d",
            summary.get("critical", 0),
            summary.get("high", 0),
            summary.get("medium", 0),
            summary.get("low", 0),
        )


def morning_brief_key(org_id: str) -> str:
    """Redis key for one organisation's brief."""
    return f"morning_brief:{org_id}"


async def _generate_morning_brief(org_id: str | None = None, now: datetime | None = None) -> RunReport:
    """One brief per organisation — for `org_id`, or for every organisation
    with a completed job in the last 24 hours when called by the scheduler.

    It used to be one brief for everyone: the last ten completed jobs of all
    organisations averaged into a single summary, sent to the LLM, and stored
    under one key that an unauthenticated route returned. Each company now gets
    a brief built only from its own jobs. Per organisation and day it runs once
    (the ledger of `services/job_runs.py`), so the catch-up after a restart cannot repeat it.
    """
    from sqlalchemy import select

    from app.database import engine, get_session_factory
    from app.models.analysis_job import AnalysisJob, JobStatus

    report = RunReport()
    if org_id is not None:
        await _generate_morning_brief_for_org(org_id)
        report.done += 1
        return report

    moment = now or datetime.now(UTC)
    period = period_for(MORNING_BRIEF, moment)
    cutoff = moment - timedelta(hours=24)
    async with get_session_factory(engine())() as db:
        org_ids = (
            await db.execute(
                select(AnalysisJob.org_id)
                .where(
                    AnalysisJob.status == JobStatus.COMPLETED,
                    AnalysisJob.completed_at >= cutoff,
                    AnalysisJob.org_id.is_not(None),
                )
                .distinct()
            )
        ).scalars().all()
    for oid in org_ids:
        # One organisation's failure must not cost the others their brief (run_guarded records it).
        await run_guarded(MORNING_BRIEF, str(oid), period, functools.partial(_morning_brief_work, str(oid)), report)
    return report


async def _morning_brief_work(org_id: str, _db: Any) -> None:
    await _generate_morning_brief_for_org(org_id)


async def _generate_morning_brief_for_org(org_id: str) -> None:
    """
    Sabah CEO brifingi — Her gün 07:00 UTC'de çalışır.

    Son 24 saatte tamamlanan analizleri toplar, akıllı alert digest çalıştırır,
    LLM ile Türkçe executive özet üretir ve Redis'e kaydeder.

    Sonuç GET /api/v1/brief/morning endpoint'inden okunabilir.
    """
    import json

    from sqlalchemy import desc, select

    from app.database import engine, get_session_factory
    from app.models.analysis_job import AnalysisJob, JobStatus
    from app.models.report import Report, ReportFormat
    from app.services import morning_brief
    from app.services.alert_router import AlertRouter, RawAlert

    logger.info("Scheduler: generating morning executive brief")
    cutoff = datetime.now(UTC) - timedelta(hours=24)

    async with get_session_factory(engine())() as db:
        result = await db.execute(
            select(AnalysisJob)
            .where(
                AnalysisJob.status == JobStatus.COMPLETED,
                AnalysisJob.completed_at >= cutoff,
                AnalysisJob.org_id == org_id,
            )
            .order_by(desc(AnalysisJob.completed_at))
            .limit(10)
        )
        jobs = result.scalars().all()

        if not jobs:
            logger.info("Scheduler: no completed jobs in last 24h — skipping brief")
            return

        # Alerts come from the uploads' reports; FIGURES do not: summing the per-upload
        # P&L double-counts overlapping uploads. They are read once from the ledger and
        # the radar (services/morning_brief.py).
        all_raw_alerts: list[RawAlert] = []
        for job in jobs:
            rep_result = await db.execute(
                select(Report)
                .where(Report.job_id == job.id, Report.report_format == ReportFormat.JSON)
                .order_by(desc(Report.created_at))
                .limit(1)
            )
            rep = rep_result.scalar_one_or_none()
            if not rep or not rep.data:
                continue

            d = rep.data
            ts = job.completed_at or datetime.now(UTC)
            for source in ("cashflow", "forecast"):
                for a in (d.get(source) or {}).get("alerts") or []:
                    all_raw_alerts.append(RawAlert(
                        level=a.get("level", "warning"),
                        message=a.get("message", ""),
                        domain="cfo", source=source,
                        job_id=job.id, timestamp=ts,
                    ))

        # Run smart alert router
        router = AlertRouter()
        decisions = router.process_alerts(all_raw_alerts)
        digest = router.build_digest(decisions)

        facts = await morning_brief.build_facts(
            db, org_id, job_count=len(jobs), critical_count=len(digest["critical"]),
            high_count=len(digest["high"]), today=datetime.now(UTC).date(),
        )
        brief_text = morning_brief.template_brief(facts)
        narrative = "template"
        if facts.has_figures:
            try:
                from app.platform.model_gateway import complete_text

                candidate = await complete_text(
                    task="short_narrative",
                    system_prompt=(
                        "Sen deneyimli bir CEO danışmanısın. Sabah brifingini Türkçe yaz: "
                        "önce tek cümlelik manşet, sonra kısa finansal özet, varsa riskler. "
                        "YALNIZCA verilen sayıları kullan; sayı türetme, yuvarlama, madde "
                        "numarası verme (• kullan). Sade, KOBİ yöneticisinin dilinde."
                    ),
                    prompt=morning_brief.llm_prompt(facts),
                    max_tokens=700,
                    org_id=org_id,
                )
                accepted = morning_brief.accept_narrative(candidate, facts)
                if accepted is not None:
                    brief_text, narrative = accepted, "llm"
                else:
                    logger.warning("Morning brief narrative rejected: a number is not a fact")
            except Exception as exc:
                logger.warning("Morning brief LLM unavailable, using the template: %s", exc)

        brief = {
            "generated_at": datetime.now(UTC).isoformat(),
            "period": "Son 24 saat",
            "job_count": len(jobs),
            "headline": brief_text.splitlines()[0] if brief_text else "",
            "brief": brief_text,
            "critical_count": len(digest["critical"]),
            "high_count": len(digest["high"]),
            "top_action": digest.get("top_action", ""),
            "digest": digest,
            "data_date": facts.data_date,
            "figures_source": morning_brief.SOURCE,
            "narrative": narrative,
        }

        # Store in Redis with 25h TTL (survives until next brief)
        try:
            from app.services.privacy.tombstone import redis_write_allowed
            from app.worker import get_arq_pool

            pool = await get_arq_pool()
            if await redis_write_allowed(org_id):
                await pool.set(morning_brief_key(org_id), json.dumps(brief), ex=90000)
            logger.info("Scheduler: morning brief generated and stored in Redis")
        except Exception as exc:
            logger.warning("Could not store morning brief in Redis: %s", exc)


async def _nightly_intelligence_run(now: datetime | None = None) -> RunReport:
    """
    Nightly Intelligence Run — Her gece 02:00 UTC'de çalışır.

    Her organizasyon için:
    1. Son 48 saatte tamamlanan CFO job'larını topla
    2. AlertRouter ile karar ver (dedup + severity scoring)
    3. NotificationService ile teslim et (Slack + email + in-app)

    Org başına gün başına en fazla 1 run: `services/job_runs.py` defteri (yeniden başlatma sonrası
    telafi çalışması aynı geceyi ikinci kez teslim etmez).
    """
    from sqlalchemy import select

    from app.database import engine, get_session_factory
    from app.models.organization import Organization
    from app.services.notification_service import NotificationService

    logger.info("Scheduler: starting nightly intelligence run")
    moment = now or datetime.now(UTC)
    period = period_for(NIGHTLY_INTELLIGENCE, moment)
    report = RunReport()
    cutoff = moment - timedelta(hours=48)

    async with get_session_factory(engine())() as db:
        org_ids = [str(o) for o in (await db.execute(select(Organization.id))).scalars().all()]
    if not org_ids:
        logger.info("Scheduler: no organizations found — skipping nightly run")
        return report

    notification_svc = NotificationService()

    async def one_org(org_id: str, db: Any) -> None:
        org = await db.get(Organization, org_id)
        if org is not None:
            await _process_org_nightly(org=org, db=db, cutoff=cutoff, notification_svc=notification_svc)

    for org_id in org_ids:
        await run_guarded(NIGHTLY_INTELLIGENCE, org_id, period, functools.partial(one_org, org_id), report)
    logger.info("Scheduler: nightly intelligence run completed (%s)", report)
    return report


async def _process_org_nightly(org, db, cutoff, notification_svc) -> None:
    """Process a single org in the nightly run."""
    from sqlalchemy import desc, select

    from app.models.analysis_job import AnalysisJob, JobStatus
    from app.models.report import Report, ReportFormat
    from app.services.alert_router import AlertRouter, RawAlert

    # Find completed jobs for this org in last 48h
    job_result = await db.execute(
        select(AnalysisJob)
        .where(
            AnalysisJob.org_id == org.id,
            AnalysisJob.status == JobStatus.COMPLETED,
            AnalysisJob.completed_at >= cutoff,
        )
        .order_by(desc(AnalysisJob.completed_at))
        .limit(5)
    )
    jobs = job_result.scalars().all()

    if not jobs:
        logger.debug("Nightly: org=%s has no recent jobs — skipping", org.id)
        return

    all_raw_alerts: list[RawAlert] = []

    for job in jobs:
        rep_result = await db.execute(
            select(Report)
            .where(
                Report.job_id == job.id,
                Report.report_format == ReportFormat.JSON,
            )
            .order_by(desc(Report.created_at))
            .limit(1)
        )
        rep = rep_result.scalar_one_or_none()
        if not rep or not rep.data:
            continue

        d = rep.data
        ts = job.completed_at or datetime.now(UTC)

        # Extract CFO alerts from all dashboard sections
        for section in ("cashflow", "forecast", "pnl", "budget"):
            for a in (d.get(section) or {}).get("alerts") or []:
                all_raw_alerts.append(RawAlert(
                    level=a.get("level", "warning"),
                    message=a.get("message", ""),
                    domain="cfo",
                    source=section,
                    job_id=job.id,
                    timestamp=ts,
                    org_id=str(org.id),
                ))

        # Extract anomaly-based alerts
        for anomaly in (d.get("anomalies") or {}).get("items") or []:
            severity = anomaly.get("severity", "medium")
            level = "critical" if severity == "critical" else (
                "error" if severity == "high" else "warning"
            )
            all_raw_alerts.append(RawAlert(
                level=level,
                message=anomaly.get("title", anomaly.get("description", "")),
                domain="cfo",
                source="anomaly",
                job_id=job.id,
                timestamp=ts,
                org_id=str(org.id),
            ))

    if not all_raw_alerts:
        logger.debug("Nightly: org=%s — no alerts extracted", org.id)
        return

    # Run smart dedup + routing
    router = AlertRouter()
    decisions = router.process_alerts(all_raw_alerts)

    actionable = [d for d in decisions if d.action.value in ("deliver", "escalate")]
    if not actionable:
        logger.debug("Nightly: org=%s — all alerts suppressed/deduped", org.id)
        return

    logger.info(
        "Nightly: org=%s — delivering %d/%d alerts",
        org.id, len(actionable), len(decisions),
    )

    # Deliver via NotificationService
    await notification_svc.deliver(
        decisions=actionable,
        org_id=str(org.id),
        org_name=org.name or f"Org {org.id}",
        db=db,
        commit=False,  # the ledger run commits these rows together with its `done` mark
    )


async def _daily_active_org_analysis() -> None:
    """
    FAZ-2: Daily intelligence run — 08:00 UTC.

    For every active org that has uploaded data in the last 30 days but
    has NOT completed a CFO analysis in the last 24 hours, enqueue a
    fresh CFO pipeline run.

    This makes the platform self-updating — orgs get daily analysis
    without any manual trigger.

    Idempotent: skips orgs that already have a recent completed job.
    """
    from datetime import timedelta

    from sqlalchemy import desc, select

    from app.database import engine, get_session_factory
    from app.models.analysis_job import AnalysisJob, JobStatus

    logger.info("Scheduler: starting daily active-org analysis run")
    now = datetime.now(UTC)
    cutoff_recent = now - timedelta(hours=24)    # skip if already ran today
    cutoff_active = now - timedelta(days=30)     # only orgs active in last 30d

    async with get_session_factory(engine())() as db:
        # Find orgs that have uploaded data recently
        active_org_result = await db.execute(
            select(AnalysisJob.org_id)
            .where(
                AnalysisJob.org_id.isnot(None),
                AnalysisJob.created_at >= cutoff_active,
            )
            .group_by(AnalysisJob.org_id)
        )
        active_org_ids = [row[0] for row in active_org_result.all()]

        if not active_org_ids:
            logger.info("Scheduler: no active orgs found — skipping daily run")
            return

        queued = 0
        skipped = 0

        for org_id in active_org_ids:
            try:
                # Check if a completed job exists in last 24h for this org
                recent_result = await db.execute(
                    select(AnalysisJob.id).where(
                        AnalysisJob.org_id == org_id,
                        AnalysisJob.status == JobStatus.COMPLETED,
                        AnalysisJob.completed_at >= cutoff_recent,
                    ).limit(1)
                )
                if recent_result.scalar_one_or_none():
                    skipped += 1
                    continue

                # Find the most recent PENDING or COMPLETED job with a file
                latest_result = await db.execute(
                    select(AnalysisJob)
                    .where(
                        AnalysisJob.org_id == org_id,
                        AnalysisJob.file_path.isnot(None),
                    )
                    .order_by(desc(AnalysisJob.created_at))
                    .limit(1)
                )
                latest_job = latest_result.scalar_one_or_none()

                if not latest_job:
                    skipped += 1
                    continue

                # Create a new analysis job pointing to the same file
                import uuid as _uuid
                new_job = AnalysisJob(
                    id=str(_uuid.uuid4()),
                    status=JobStatus.PENDING,
                    filename=latest_job.filename,
                    file_path=latest_job.file_path,
                    file_type=latest_job.file_type,
                    user_id=latest_job.user_id,
                    org_id=org_id,
                )
                db.add(new_job)
                await db.flush()  # get the new_job.id

                from app.worker import enqueue_analysis
                await enqueue_analysis(new_job.id)
                queued += 1

                logger.info(
                    "Scheduler: daily run — enqueued job=%s for org=%s",
                    new_job.id, org_id,
                )

            except Exception as exc:
                logger.error(
                    "Scheduler: daily run failed for org=%s: %s", org_id, exc
                )

        await db.commit()
        logger.info(
            "Scheduler: daily run complete — queued=%d skipped=%d total_orgs=%d",
            queued, skipped, len(active_org_ids),
        )


async def _purge_expired_guests(db: Any, *, ttl_hours: int) -> int:
    """
    D4 çekirdeği: TTL'ı dolmuş konuk org'larının workspace'ini purge eder.

    Konuklar /demo/guest parmak iziyle tanınır (slug `demo-<12hex>` + misafir
    description) — golden ve kullanıcı org'ları regex/description'a takılmaz,
    yine de son savunma olarak `is_guest_org` uygulanır. Dönüş: purge edilen
    konuk sayısı.
    """
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select

    from app.models.organization import Organization
    from app.services.demo_template import (
        GUEST_SLUG_RE,
        is_guest_org,
        purge_demo_workspace,
    )

    cutoff = datetime.now(UTC) - timedelta(hours=ttl_hours)
    orgs = (
        await db.execute(
            select(Organization).where(
                Organization.created_at < cutoff,
                Organization.is_demo_guest.is_(True),
            )
        )
    ).scalars().all()

    purged = 0
    for org in orgs:
        if not is_guest_org(org) or not GUEST_SLUG_RE.match(org.slug or ""):
            continue  # belt & braces: yalnızca kesin konuklar
        counts = await purge_demo_workspace(db, str(org.id))
        purged += 1
        logger.info("Demo TTL purge: org=%s slug=%s counts=%s", org.id, org.slug, counts)
    if purged:
        logger.info("Demo TTL purge: %d konuk workspace temizlendi", purged)
    return purged


async def _demo_guest_ttl_purge() -> None:
    """
    D4: saatlik cron — TTL'ı dolmuş konuk demo workspace'leri otomatik reset
    (DEMO_PLAN §D4 "konuk session bitiminde auto-reset"). demo_mode kapalıysa
    no-op: üretimde cron kaydı zaten yapılmaz.
    """
    try:
        from app.config import get_settings
        from app.database import engine, get_session_factory

        settings = get_settings()
        if not settings.demo_mode:
            return
        async with get_session_factory(engine())() as db:
            await _purge_expired_guests(db, ttl_hours=settings.demo_guest_ttl_hours)
    except Exception as exc:
        logger.error("Demo TTL purge hatasi: %s", exc)


# misfire_grace_time (seconds): how late a tick may still run when the event loop was busy or blocked.
# It does NOT cover a restart: APScheduler keeps no jobs across one, so a process that was down at 07:00
# never sees that tick at all. That case is `_schedule_catch_up` below (ledger + windows,
# services/schedule_runner.py). The numbers are therefore sized to "a stall", per job class:
GRACE_TICK = 240       # every 5 minutes: the next tick is the retry
GRACE_HOURLY = 1800    # hourly: late by up to half an hour is still this hour's work
GRACE_DAILY = 3600     # daily/weekly: an hour of stall still runs it; beyond that catch-up decides
# coalesce=True everywhere: a backlog of missed ticks of one job runs once, never in a burst.
# max_instances=1 everywhere: a slow run is never overlapped by the next tick of the same job.


def _add(
    scheduler: AsyncIOScheduler, fn: Callable[..., Awaitable[object]], job_id: str, trigger: Any, *,
    grace: int, ttl: int = 1800,
) -> None:
    scheduler.add_job(
        _exclusive(fn, job_id, ttl=ttl), trigger, id=job_id, replace_existing=True,
        max_instances=1, coalesce=True, misfire_grace_time=grace,
    )


def get_scheduler() -> AsyncIOScheduler:
    """Return the singleton scheduler (create if needed).

    Every job is wrapped in `_exclusive`: several uvicorn workers each start
    their own APScheduler, and one cron tick must run once — not once per
    process. The jobs that matter to a company (briefing, morning brief, nightly run, KRI scan) are
    additionally guarded by the run ledger and caught up after a restart.
    """
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone="UTC")
        sched = _scheduler

        _add(sched, _scan_recent_jobs, "daily_anomaly_scan", CronTrigger(hour=6, minute=0), grace=GRACE_DAILY)
        # Weekly on Monday 07:00 UTC — the Monday briefing and the summary log (caught up: MONDAY_BRIEFING)
        _add(sched, _weekly_summary, "weekly_summary", CronTrigger(day_of_week="mon", hour=7, minute=0),
             grace=GRACE_DAILY)
        # Daily at 07:00 UTC — morning CEO brief (stored in Redis)
        _add(sched, _generate_morning_brief, "morning_brief", CronTrigger(hour=7, minute=0), grace=GRACE_DAILY)
        # Nightly at 02:00 UTC — full intelligence run + notifications
        _add(sched, _nightly_intelligence_run, "nightly_intelligence_run", CronTrigger(hour=2, minute=0),
             grace=GRACE_DAILY, ttl=3600)
        # FAZ-2: Daily at 08:00 UTC — re-analyze active orgs automatically
        _add(sched, _daily_active_org_analysis, "daily_active_org_analysis", CronTrigger(hour=8, minute=0),
             grace=GRACE_DAILY)
        # PROACTIVE: Every hour (:15) — KRI scan + alert dispatch (a stale one is skipped, never queued up)
        _add(sched, _hourly_proactive_kri_scan, "hourly_proactive_kri_scan", CronTrigger(minute=15),
             grace=GRACE_HOURLY)
        # ERP SYNC: hourly check; each integration is pulled when its own
        # interval (daily or weekly, chosen on the integrations page) is due.
        _add(sched, _daily_erp_sync, "daily_erp_sync", CronTrigger(minute=30), grace=GRACE_HOURLY)
        # DQ-5: Hourly — check and run due SyncSchedules (ERP/OB/eFatura)
        _add(sched, _run_scheduled_syncs, "scheduled_data_syncs", CronTrigger(minute=45), grace=GRACE_HOURLY)
        # RAG maintenance: her 2 saatte bir eksik chunk indexlerini tamamla.
        _add(sched, _rag_backfill_maintenance, "rag_backfill_maintenance", CronTrigger(minute=5, hour="*/2"),
             grace=GRACE_DAILY)
        # P4: hourly — `schedule` trigger rules, evaluated once per UTC day
        # (the date is the idempotency key, so a missed midnight still runs).
        _add(sched, _trigger_schedule_tick, "trigger_schedule_tick", CronTrigger(minute=10), grace=GRACE_HOURLY,
             ttl=3000)
        # C9: every 5 minutes - the outbox sends pending messages and records each outcome.
        _add(sched, _deliver_outbox, "outbox_delivery", CronTrigger(minute="*/5"), grace=GRACE_TICK, ttl=240)
        # O5: daily, before the Monday briefing (07:00) - the forecast log.
        _add(sched, _record_radar_forecasts, "radar_forecast_log", CronTrigger(hour=5, minute=30), grace=GRACE_DAILY)
        # USAGE: Nightly at 03:00 UTC — prune old usage_events (>90 days)
        _add(sched, _nightly_usage_prune, "nightly_usage_prune", CronTrigger(hour=3, minute=0), grace=GRACE_DAILY)

        # Restart safety: shortly after start and every 10 minutes, run what was due, is inside its window
        # and has no finished ledger row (also retries a run that failed or whose process died).
        start_in = datetime.now(UTC) + timedelta(seconds=30)
        sched.add_job(
            _schedule_catch_up, IntervalTrigger(minutes=10, start_date=start_in), id="schedule_catch_up",
            replace_existing=True, max_instances=1, coalesce=True, misfire_grace_time=GRACE_TICK,
            next_run_time=start_in,
        )
        # Operator alerts (failed backup, failing destinations, preflight warnings): at start, then every 15 minutes.
        sched.add_job(
            _ops_watch, IntervalTrigger(minutes=15, start_date=start_in), id="ops_watch",
            replace_existing=True, max_instances=1, coalesce=True, misfire_grace_time=GRACE_TICK,
            next_run_time=start_in,
        )

        # DDIA Ch.1/Ch.7: a claim without an expiry is not a claim. Every 10
        # minutes, fail analysis jobs whose lease expired (the worker died
        # mid-run) and agent_runs left `running` by a crash — without this,
        # a killed worker leaves a job `analyzing` forever.
        from app.config import get_settings

        if get_settings().reaper_enabled:
            # TTL (9 min) < interval (10 min): the lock is free by the next tick.
            _add(sched, _run_stuck_job_reaper, "stuck_job_reaper", CronTrigger(minute="*/10"), grace=GRACE_TICK,
                 ttl=540)

        # D4: hourly — konuk demo workspace'leri TTL dolunca purge (auto-reset).
        # demo_mode kapalıysa hiç kaydedilmez (production'da cron tetiklenmez).
        if get_settings().demo_mode:
            _add(sched, _demo_guest_ttl_purge, "demo_guest_ttl_purge", CronTrigger(minute=25), grace=GRACE_HOURLY)

    from app.services.privacy.jobs import register_privacy_jobs

    register_privacy_jobs(_scheduler, _exclusive)  # KVKK: erasure executor (and the retention purge)
    return _scheduler


async def _schedule_catch_up() -> None:
    """Run the due-but-unfinished runs of the jobs in `schedule_runner.SPECS` (never raises)."""
    try:
        from app.services.schedule_runner import catch_up

        await catch_up()
    except Exception:
        logger.exception("schedule catch-up failed")


async def _ops_watch() -> None:
    """Tell the platform operators about what only a person can fix (never raises)."""
    try:
        from app.services.ops_watch import watch

        await watch()
    except Exception:
        logger.exception("ops watch failed")


async def _hourly_proactive_kri_scan(now: datetime | None = None) -> RunReport:
    """
    Saatlik KRI tarama ve proaktif alert dispatch.
    Her org icin Risk Kernel calistirir, esik asiminda cascade + alert.

    Once per hour (ledger period = the hour); a failed scan is retried within the same hour by the
    catch-up, an older one is skipped (`services/schedule_runner.py` windows).
    """
    report = RunReport()
    slot = period_for(HOURLY_KRI_SCAN, now)

    async def scan(db: Any) -> None:
        from app.agents.orchestration.proactive_alerts import get_proactive_orchestrator

        orchestrator = get_proactive_orchestrator(db=db, slot=slot)
        result = await orchestrator.run_scheduled_scan()
        # An alert was rolled back or an org's scan raised: the slot is not done. The other orgs' alerts are
        # committed already; the retry (ledger attempts, operator alert) repeats none of them (slot-derived ids).
        if orchestrator.save_failures or orchestrator.failed_orgs:
            raise RuntimeError(
                f"{orchestrator.save_failures} alert(s) could not be saved; "
                f"scan failed for {len(orchestrator.failed_orgs)} org(s)"
            )
        if result.get("total_alerts", 0) > 0:
            logger.info(
                "Proactive KRI scan: orgs=%d alerts=%d", result.get("scanned", 0), result.get("total_alerts", 0),
            )

    await run_guarded(HOURLY_KRI_SCAN, GLOBAL, slot, scan, report)
    return report


async def _trigger_schedule_tick() -> None:
    """Hourly: fire today's `schedule` trigger rules (once per UTC day per rule)."""
    try:
        from app.database import engine, get_session_factory
        from app.services.triggers.sources import emit_schedule_tick

        async with get_session_factory(engine())() as db:
            outcomes = await emit_schedule_tick(db)
        fired = sum(1 for o in outcomes if o.status == "fired")
        if outcomes:
            logger.info(
                "Trigger schedule tick: %d evaluated, %d fired", len(outcomes), fired
            )
    except Exception as exc:
        logger.error("Trigger schedule tick error: %s", exc)


async def _nightly_usage_prune() -> None:
    """
    Nightly: enqueue usage_events prune on the maintenance queue.
    """
    try:
        from app.worker import enqueue_maintenance_job

        enqueued = await enqueue_maintenance_job("run_usage_prune_maintenance")
        if enqueued:
            logger.info("Usage prune enqueued to maintenance queue")
    except Exception as exc:
        logger.error("Usage prune enqueue hatasi: %s", exc)


async def _daily_erp_sync() -> None:
    """
    Gunluk ERP sync: Parasut gibi OAuth tabanli entegrasyonlari sync et.
    CSV tabanli entegrasyonlar (Logo Tiger, Mikro) manual trigger bekler.
    """
    try:
        from app.agents.orchestration.erp_sync_runner import run_scheduled_erp_sync
        from app.database import engine, get_session_factory
        async with get_session_factory(engine())() as db:
            result = await run_scheduled_erp_sync(db=db)
            logger.info("Daily ERP sync: synced=%d", result.get("synced", 0))
    except Exception as exc:
        logger.error("Daily ERP sync hatasi: %s", exc)


async def _run_scheduled_syncs() -> None:
    """
    DQ-5: Run all due SyncSchedule entries.
    Pulls data from ERP/Open Banking/eFatura sources and starts analysis jobs.
    Called every hour — each SyncSchedule checks its own frequency/hour internally.
    """
    try:
        from app.config import get_settings
        from app.database import engine, get_session_factory
        from app.services.scheduled_sync import run_due_syncs
        settings = get_settings()
        async with get_session_factory(engine())() as db:
            results = await run_due_syncs(db=db, settings=settings)
            if results:
                logger.info(
                    "ScheduledSync: ran %d sync(s) — %d success, %d failed",
                    len(results),
                    sum(1 for r in results if r.status == "success"),
                    sum(1 for r in results if r.status == "failed"),
                )
    except Exception as exc:
        logger.error("ScheduledSync runner error: %s", exc)


async def _rag_backfill_maintenance() -> None:
    """
    Enqueue RAG chunk backfill on the maintenance queue (analysis queue stays free).
    """
    try:
        from app.worker import enqueue_maintenance_job

        enqueued = await enqueue_maintenance_job("run_rag_backfill_maintenance")
        if enqueued:
            logger.info("RAG backfill enqueued to maintenance queue")
    except Exception as exc:
        logger.error("RAG backfill enqueue error: %s", exc)


def start_scheduler(process: str = "api") -> None:
    """Start APScheduler if `process` is the process type that owns the crons.

    `process` is the caller's kind ("api" from the FastAPI lifespan, "worker"
    from the arq analysis worker); `scheduler_process` names the owner. Every
    job is still wrapped in `_exclusive`, so replicas of the owner never
    double-run a tick.
    """
    from app.config import get_settings

    settings = get_settings()
    if not settings.scheduler_enabled:
        logger.info("CFO Scheduler disabled (scheduler_enabled=false)")
        return
    if settings.scheduler_process != process:
        logger.info(
            "CFO Scheduler not started in %s process (owned by %s)",
            process,
            settings.scheduler_process,
        )
        return
    scheduler = get_scheduler()
    if not scheduler.running:
        scheduler.start()
        logger.info("CFO Scheduler started — daily scan at 06:00 UTC")


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("CFO Scheduler stopped")
