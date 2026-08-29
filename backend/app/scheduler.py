"""
CFO Scheduler — APScheduler ile periyodik görevler.

Görevler:
- Günlük: Son 7 gündeki tüm completed job'ları tara, anomali yoksa çalıştır
- Haftalık: Haftalık özet rapor üret (gelecek fazda e-posta ile gönderilecek)

FastAPI lifespan'ında başlatılır, uygulama kapanışında durdurulur.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

# Module-level scheduler singleton
_scheduler: AsyncIOScheduler | None = None


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
            else:
                logger.debug("Scheduler: job=%s — no anomalies found", job.id)


async def _weekly_summary() -> None:
    """
    Haftalık görev: Anomali özeti logla.
    Gelecek fazda: e-posta ile CFO'ya gönder.
    """
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


async def _generate_morning_brief() -> None:
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
    from app.services.alert_router import AlertRouter, RawAlert

    logger.info("Scheduler: generating morning executive brief")
    cutoff = datetime.now(UTC) - timedelta(hours=24)

    async with get_session_factory(engine())() as db:
        result = await db.execute(
            select(AnalysisJob)
            .where(
                AnalysisJob.status == JobStatus.COMPLETED,
                AnalysisJob.completed_at >= cutoff,
            )
            .order_by(desc(AnalysisJob.completed_at))
            .limit(10)
        )
        jobs = result.scalars().all()

        if not jobs:
            logger.info("Scheduler: no completed jobs in last 24h — skipping brief")
            return

        # Aggregate dashboard data and alerts
        all_raw_alerts: list[RawAlert] = []
        all_pnl: list[dict] = []
        all_cashflow: list[dict] = []
        all_forecast: list[dict] = []

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

            for a in (d.get("cashflow") or {}).get("alerts") or []:
                all_raw_alerts.append(RawAlert(
                    level=a.get("level", "warning"),
                    message=a.get("message", ""),
                    domain="cfo", source="cashflow",
                    job_id=job.id, timestamp=ts,
                ))
            for a in (d.get("forecast") or {}).get("alerts") or []:
                all_raw_alerts.append(RawAlert(
                    level=a.get("level", "warning"),
                    message=a.get("message", ""),
                    domain="cfo", source="forecast",
                    job_id=job.id, timestamp=ts,
                ))

            if d.get("pnl"):
                all_pnl.append(d["pnl"])
            if d.get("cashflow"):
                all_cashflow.append(d["cashflow"])
            if d.get("forecast"):
                all_forecast.append(d["forecast"])

        # Run smart alert router
        router = AlertRouter()
        decisions = router.process_alerts(all_raw_alerts)
        digest = router.build_digest(decisions)

        # Build summary context for LLM
        avg_net_margin = (
            sum(p.get("net_margin", 0) for p in all_pnl) / len(all_pnl)
            if all_pnl else 0
        )
        total_revenue = sum(p.get("revenue", 0) for p in all_pnl)
        net_cash_changes = [cf.get("net_change", 0) for cf in all_cashflow]
        avg_cash_change = sum(net_cash_changes) / len(net_cash_changes) if net_cash_changes else 0

        # Base runway from first forecast
        runway = None
        if all_forecast:
            base_sc = (all_forecast[0].get("scenarios") or {}).get("base") or {}
            runway = base_sc.get("runway_months")

        try:
            from app.platform.model_gateway import complete_text

            critical_msgs = "\n".join(
                f"• {a['message']}" for a in digest["critical"][:3]
            ) or "Kritik uyarı yok."

            high_msgs = "\n".join(
                f"• {a['message']}" for a in digest["high"][:3]
            ) or "Yüksek öncelikli uyarı yok."

            context = (
                f"Analiz edilen şirket sayısı: {len(jobs)}\n"
                f"Ortalama net kâr marjı: %{avg_net_margin*100:.1f}\n"
                f"Toplam ciro: {total_revenue/100:,.0f} TL\n"
                f"Ortalama nakit değişimi: {avg_cash_change/100:,.0f} TL\n"
                f"Nakit ömrü (baz senaryo): {runway or 'bilinmiyor'} ay\n\n"
                f"Kritik uyarılar:\n{critical_msgs}\n\n"
                f"Yüksek öncelikli uyarılar:\n{high_msgs}"
            )

            brief_text = (await complete_text(
                task="short_narrative",
                system_prompt=(
                    "Sen deneyimli bir CEO danışmanısın. "
                    "Sabah brifingini Türkçe yaz. Yapı:\n"
                    "• Manşet (1 cümle — bugünün en kritik durumu)\n"
                    "• Finansal özet (2-3 cümle)\n"
                    "• Kritik riskler (madde madde, varsa)\n"
                    "• Bugün yapılması gereken en önemli 3 eylem\n"
                    "Sade, doğrudan, KOBİ yöneticisinin anlayacağı dilde."
                ),
                prompt=f"Veri:\n{context}",
                max_tokens=700,
            )).strip()
        except Exception as exc:
            logger.warning("Morning brief LLM failed: %s", exc)
            brief_text = (
                f"Özet: {len(jobs)} analiz tamamlandı. "
                f"Net kâr marjı: %{avg_net_margin*100:.1f}. "
                f"Kritik uyarı: {len(digest['critical'])}. "
                f"Nakit ömrü: {runway or 'bilinmiyor'} ay."
            )

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
        }

        # Store in Redis with 25h TTL (survives until next brief)
        try:
            from app.worker import get_arq_pool
            pool = await get_arq_pool()
            await pool.set("morning_brief:latest", json.dumps(brief), ex=90000)
            logger.info("Scheduler: morning brief generated and stored in Redis")
        except Exception as exc:
            logger.warning("Could not store morning brief in Redis: %s", exc)


async def _nightly_intelligence_run() -> None:
    """
    Nightly Intelligence Run — Her gece 02:00 UTC'de çalışır.

    Her organizasyon için:
    1. Son 48 saatte tamamlanan CFO job'larını topla
    2. AlertRouter ile karar ver (dedup + severity scoring)
    3. NotificationService ile teslim et (Slack + email + in-app)

    Org başına max 1 run — idempotent (aynı fingerprint tekrar teslim edilmez).
    """
    from sqlalchemy import select

    from app.database import engine, get_session_factory
    from app.models.organization import Organization
    from app.services.notification_service import NotificationService

    logger.info("Scheduler: starting nightly intelligence run")
    cutoff = datetime.now(UTC) - timedelta(hours=48)

    async with get_session_factory(engine())() as db:
        # Get all orgs
        org_result = await db.execute(select(Organization))
        orgs = org_result.scalars().all()

        if not orgs:
            logger.info("Scheduler: no organizations found — skipping nightly run")
            return

        notification_svc = NotificationService()

        for org in orgs:
            try:
                await _process_org_nightly(
                    org=org,
                    db=db,
                    cutoff=cutoff,
                    notification_svc=notification_svc,
                )
            except Exception as exc:
                logger.error(
                    "Nightly run failed for org=%s: %s", org.id, exc, exc_info=True
                )

        logger.info("Scheduler: nightly intelligence run completed for %d orgs", len(orgs))


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


def get_scheduler() -> AsyncIOScheduler:
    """Return the singleton scheduler (create if needed)."""
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone="UTC")

        # Daily at 06:00 UTC — scan recent jobs for anomalies
        _scheduler.add_job(
            _scan_recent_jobs,
            CronTrigger(hour=6, minute=0),
            id="daily_anomaly_scan",
            replace_existing=True,
            max_instances=1,
        )

        # Weekly on Monday 07:00 UTC — summary log
        _scheduler.add_job(
            _weekly_summary,
            CronTrigger(day_of_week="mon", hour=7, minute=0),
            id="weekly_summary",
            replace_existing=True,
            max_instances=1,
        )

        # Daily at 07:00 UTC — morning CEO brief (stored in Redis)
        _scheduler.add_job(
            _generate_morning_brief,
            CronTrigger(hour=7, minute=0),
            id="morning_brief",
            replace_existing=True,
            max_instances=1,
        )

        # Nightly at 02:00 UTC — full intelligence run + notifications
        _scheduler.add_job(
            _nightly_intelligence_run,
            CronTrigger(hour=2, minute=0),
            id="nightly_intelligence_run",
            replace_existing=True,
            max_instances=1,
        )

        # FAZ-2: Daily at 08:00 UTC — re-analyze active orgs automatically
        _scheduler.add_job(
            _daily_active_org_analysis,
            CronTrigger(hour=8, minute=0),
            id="daily_active_org_analysis",
            replace_existing=True,
            max_instances=1,
        )

        # PROACTIVE: Every hour — KRI scan + alert dispatch
        _scheduler.add_job(
            _hourly_proactive_kri_scan,
            CronTrigger(minute=15),   # Her saatin 15. dakikasında
            id="hourly_proactive_kri_scan",
            replace_existing=True,
            max_instances=1,
        )

        # ERP SYNC: Daily at 06:30 UTC — scheduled ERP sync for active integrations
        _scheduler.add_job(
            _daily_erp_sync,
            CronTrigger(hour=6, minute=30),
            id="daily_erp_sync",
            replace_existing=True,
            max_instances=1,
        )

        # DQ-5: Hourly — check and run due SyncSchedules (ERP/OB/eFatura)
        _scheduler.add_job(
            _run_scheduled_syncs,
            CronTrigger(minute=45),   # Her saatin 45. dakikasında
            id="scheduled_data_syncs",
            replace_existing=True,
        )

        # RAG maintenance: her 2 saatte bir eksik chunk indexlerini tamamla.
        _scheduler.add_job(
            _rag_backfill_maintenance,
            CronTrigger(minute=5, hour="*/2"),
            id="rag_backfill_maintenance",
            replace_existing=True,
            max_instances=1,
        )

        # USAGE: Nightly at 03:00 UTC — prune old usage_events (>90 days)
        _scheduler.add_job(
            _nightly_usage_prune,
            CronTrigger(hour=3, minute=0),
            id="nightly_usage_prune",
            replace_existing=True,
            max_instances=1,
        )

    return _scheduler


async def _hourly_proactive_kri_scan() -> None:
    """
    Saatlik KRI tarama ve proaktif alert dispatch.
    Her org icin Risk Kernel calistirir, esik asiminda cascade + alert.
    """
    try:
        from app.agents.orchestration.proactive_alerts import get_proactive_orchestrator
        from app.database import engine, get_session_factory
        async with get_session_factory(engine())() as db:
            orchestrator = get_proactive_orchestrator(db=db)
            result       = await orchestrator.run_scheduled_scan()
            if result.get("total_alerts", 0) > 0:
                logger.info(
                    "Proactive KRI scan: orgs=%d alerts=%d",
                    result.get("scanned", 0), result.get("total_alerts", 0),
                )
    except Exception as exc:
        logger.error("Hourly proactive scan hatasi: %s", exc)


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


def start_scheduler() -> None:
    scheduler = get_scheduler()
    if not scheduler.running:
        scheduler.start()
        logger.info("CFO Scheduler started — daily scan at 06:00 UTC")


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("CFO Scheduler stopped")
