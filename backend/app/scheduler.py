"""
CFO Scheduler — APScheduler ile periyodik görevler.

Görevler:
- Günlük: Son 7 gündeki tüm completed job'ları tara, anomali yoksa çalıştır
- Haftalık: Haftalık özet rapor üret (gelecek fazda e-posta ile gönderilecek)

FastAPI lifespan'ında başlatılır, uygulama kapanışında durdurulur.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

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
    from app.database import get_session_factory, engine
    from app.models.analysis_job import AnalysisJob, JobStatus
    from app.models.anomaly import Anomaly
    from app.models.transaction import Transaction
    from app.models.report import Report, ReportFormat
    from app.agents.anomaly_agent import (
        detect_duplicates, detect_unusual_amounts, detect_vendor_concentration,
        detect_expense_spikes, detect_round_numbers, detect_negative_cashflow_streak,
        _generate_anomaly_narrative,
    )
    from app.config import get_settings
    from sqlalchemy import select, func

    settings = get_settings()
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)

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
                    Anomaly.created_at >= datetime.now(timezone.utc).replace(
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
    from app.database import get_session_factory, engine
    from app.models.anomaly import Anomaly
    from sqlalchemy import select, func

    cutoff = datetime.now(timezone.utc) - timedelta(days=7)

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
    from app.database import get_session_factory, engine
    from app.models.analysis_job import AnalysisJob, JobStatus
    from app.models.report import Report, ReportFormat
    from app.services.alert_router import AlertRouter, RawAlert
    from app.config import get_settings
    from sqlalchemy import select, desc
    import json

    logger.info("Scheduler: generating morning executive brief")
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    settings = get_settings()

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
            ts = job.completed_at or datetime.now(timezone.utc)

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
            from langchain_openai import ChatOpenAI
            from langchain_core.messages import HumanMessage, SystemMessage

            llm = ChatOpenAI(
                model=settings.llm_model,
                temperature=0.2,
                max_tokens=700,
                api_key=settings.openai_api_key,
                base_url=settings.llm_base_url or None,
            )

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

            response = await llm.ainvoke([
                SystemMessage(content=(
                    "Sen deneyimli bir CEO danışmanısın. "
                    "Sabah brifingini Türkçe yaz. Yapı:\n"
                    "• Manşet (1 cümle — bugünün en kritik durumu)\n"
                    "• Finansal özet (2-3 cümle)\n"
                    "• Kritik riskler (madde madde, varsa)\n"
                    "• Bugün yapılması gereken en önemli 3 eylem\n"
                    "Sade, doğrudan, KOBİ yöneticisinin anlayacağı dilde."
                )),
                HumanMessage(content=f"Veri:\n{context}"),
            ])
            brief_text = response.content.strip()
        except Exception as exc:
            logger.warning("Morning brief LLM failed: %s", exc)
            brief_text = (
                f"Özet: {len(jobs)} analiz tamamlandı. "
                f"Net kâr marjı: %{avg_net_margin*100:.1f}. "
                f"Kritik uyarı: {len(digest['critical'])}. "
                f"Nakit ömrü: {runway or 'bilinmiyor'} ay."
            )

        brief = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
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


def get_scheduler() -> AsyncIOScheduler:
    """Return the singleton scheduler (create if needed)."""
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone="UTC")

        # Daily at 06:00 UTC — scan recent jobs
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

    return _scheduler


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
