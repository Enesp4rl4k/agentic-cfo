"""
Alert Digest API — Phase 5.2

GET  /api/v1/alerts/digest/{job_id}
     Daily alert digest: critical + high + aggregated groups + suppressed count.
     Runs all job alerts through the SmartAlertRouter before returning.

GET  /api/v1/alerts/digest/latest
     Latest digest across all recent jobs (last 24h).

POST /api/v1/alerts/acknowledge/{job_id}/{alert_hash}
     Mark an alert as acknowledged (stores in Redis or DB).
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.access import owned_job
from app.api.auth import get_current_user
from app.database import get_db
from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.report import Report, ReportFormat
from app.models.user import User
from app.services.alert_router import AlertRouter, RawAlert

router = APIRouter()
logger = logging.getLogger(__name__)

_alert_router = AlertRouter(
    dedup_ttl_hours=4,
    aggregation_threshold=3,
    escalate_threshold=0.75,
)


def _extract_raw_alerts(job: AnalysisJob, dashboard_data: dict[str, Any]) -> list[RawAlert]:
    """
    Extract RawAlert objects from a completed analysis job's dashboard JSON.
    Combines: cashflow alerts, forecast alerts, anomaly narratives, triggered_alerts.
    """
    raw: list[RawAlert] = []
    job_id = job.id
    ts = job.completed_at or job.updated_at or datetime.now(UTC)

    # ── CFO pipeline alerts ────────────────────────────────────────────────
    cashflow = dashboard_data.get("cashflow") or {}
    for a in cashflow.get("alerts") or []:
        raw.append(RawAlert(
            level=a.get("level", "warning"),
            message=a.get("message", ""),
            domain="cfo",
            source="cashflow",
            job_id=job_id,
            timestamp=ts,
        ))

    forecast = dashboard_data.get("forecast") or {}
    for a in forecast.get("alerts") or []:
        raw.append(RawAlert(
            level=a.get("level", "warning"),
            message=a.get("message", ""),
            domain="cfo",
            source="forecast",
            job_id=job_id,
            timestamp=ts,
        ))

    # Monte Carlo runway risk alert
    mc = forecast.get("monte_carlo") or {}
    if mc.get("runway_risk_pct", 0) > 30:
        raw.append(RawAlert(
            level="critical" if mc["runway_risk_pct"] > 60 else "warning",
            message=(
                f"Monte Carlo: {mc['runway_risk_pct']:.0f}% olasılıkla "
                f"6 ay içinde nakit sıkıntısı yaşanabilir."
            ),
            domain="cfo",
            source="monte_carlo",
            job_id=job_id,
            timestamp=ts,
            evidence={"runway_risk_pct": mc["runway_risk_pct"]},
        ))

    # ── Job-level triggered alerts ─────────────────────────────────────────
    for a in job.logs or []:
        if not a.get("ok") and a.get("detail"):
            raw.append(RawAlert(
                level="warning",
                message=f"Agent '{a.get('step')}' hatası: {a.get('detail')}",
                domain="cfo",
                source=a.get("step", "pipeline"),
                job_id=job_id,
                timestamp=ts,
            ))

    return raw


def _build_digest_response(
    job_id: str,
    raw_alerts: list[RawAlert],
    period: str = "son analiz",
) -> dict[str, Any]:
    """Run alerts through router and return structured digest."""
    decisions = _alert_router.process_alerts(raw_alerts, recent_history=[])
    digest = _alert_router.build_digest(decisions)

    return {
        "job_id":   job_id,
        "period":   period,
        "generated_at": datetime.now(UTC).isoformat(),
        "summary": (
            f"{len(digest['critical'])} kritik, "
            f"{len(digest['high'])} yüksek, "
            f"{digest['suppressed_count']} tekrar bastırıldı"
        ),
        **digest,
    }


@router.get("/alerts/digest/{job_id}")
async def get_alert_digest(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    job: AnalysisJob = Depends(owned_job),
) -> dict[str, Any]:
    """
    Smart alert digest for a specific analysis job.

    Runs all job alerts through the AlertRouter (dedup + aggregation + routing)
    and returns a structured digest — critical, high, aggregated, suppressed count.

    Use this instead of raw alert arrays to avoid alert fatigue.
    """
    job = await db.get(AnalysisJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")

    if job.status not in (JobStatus.COMPLETED, JobStatus.AWAITING_REVIEW):
        raise HTTPException(
            status_code=409,
            detail=f"Job status is '{job.status}' — digest only available for completed jobs.",
        )

    # Load dashboard JSON
    result = await db.execute(
        select(Report)
        .where(Report.job_id == job_id, Report.report_format == ReportFormat.JSON)
        .order_by(desc(Report.created_at))
        .limit(1)
    )
    report = result.scalar_one_or_none()
    dashboard_data = report.data if report else {}

    raw_alerts = _extract_raw_alerts(job, dashboard_data)
    digest = _build_digest_response(
        job_id=job_id,
        raw_alerts=raw_alerts,
        period=job.completed_at.strftime("%d %b %Y %H:%M") if job.completed_at else "son analiz",
    )

    return {"data": digest, "error": None}


@router.get("/alerts/digest/latest")
async def get_latest_digest(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    hours: int = 24,
) -> dict[str, Any]:
    """
    Aggregate alert digest across all jobs completed in the last N hours.

    Useful for a daily morning briefing: "What happened overnight?"
    """
    since = datetime.now(UTC) - timedelta(hours=hours)

    q = (
        select(AnalysisJob)
        .where(
            AnalysisJob.status == JobStatus.COMPLETED,
            AnalysisJob.completed_at >= since,
        )
        .order_by(desc(AnalysisJob.completed_at))
        .limit(20)
    )
    # Scope to org
    if current_user.org_id:
        q = q.where(AnalysisJob.org_id == current_user.org_id)

    result = await db.execute(q)
    jobs = result.scalars().all()

    if not jobs:
        return {
            "data": {
                "period": f"Son {hours} saat",
                "generated_at": datetime.now(UTC).isoformat(),
                "summary": "Bu dönemde tamamlanan analiz yok.",
                "critical": [],
                "high": [],
                "aggregated": [],
                "suppressed_count": 0,
                "total_actionable": 0,
                "top_action": "Analiz verisi yok.",
            },
            "error": None,
        }

    # Batch-fetch all reports in a single query (resolving N+1 anti-pattern)
    job_ids = [j.id for j in jobs]
    report_result = await db.execute(
        select(Report)
        .where(Report.job_id.in_(job_ids), Report.report_format == ReportFormat.JSON)
        .order_by(desc(Report.created_at))
    )
    all_reports = report_result.scalars().all()
    reports_by_job: dict[str, Any] = {}
    for rep in all_reports:
        if rep.job_id not in reports_by_job:
            reports_by_job[rep.job_id] = rep.data or {}

    all_raw: list[RawAlert] = []
    for job in jobs:
        dashboard_data = reports_by_job.get(job.id, {})
        all_raw.extend(_extract_raw_alerts(job, dashboard_data))

    # Route with dedup — alerts from same domain/message in different jobs are deduped
    decisions = _alert_router.process_alerts(all_raw, recent_history=[])
    digest = _alert_router.build_digest(decisions)

    return {
        "data": {
            "period": f"Son {hours} saat",
            "job_count": len(jobs),
            "generated_at": datetime.now(UTC).isoformat(),
            "summary": (
                f"{len(jobs)} analiz tamamlandı — "
                f"{len(digest['critical'])} kritik, "
                f"{len(digest['high'])} yüksek, "
                f"{digest['suppressed_count']} tekrar bastırıldı"
            ),
            **digest,
        },
        "error": None,
    }


@router.get("/alerts/top/{job_id}")
async def get_top_alerts(
    job_id: str,
    limit: int = 3,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    job: AnalysisJob = Depends(owned_job),
) -> dict[str, Any]:
    """
    Return the top N most actionable alerts for a job — prioritized for the
    "What should I do now?" ActionBar widget on the dashboard.

    Scoring:
      - critical > high > warning > info (40/30/20/10 base points)
      - Source bonus: anomaly +15, cashflow +10, forecast +5
      - Monte Carlo runway risk bonus: up to +20
    """
    job = await db.get(AnalysisJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")

    result = await db.execute(
        select(Report)
        .where(Report.job_id == job_id, Report.report_format == ReportFormat.JSON)
        .order_by(desc(Report.created_at))
        .limit(1)
    )
    report = result.scalar_one_or_none()
    dashboard_data = report.data if report else {}

    raw_alerts = _extract_raw_alerts(job, dashboard_data)
    if not raw_alerts:
        return {"data": {"top_alerts": [], "total_raw": 0}, "error": None}

    # Score each raw alert
    _LEVEL_SCORE = {"critical": 40, "error": 35, "warning": 20, "info": 10}
    _SOURCE_BONUS = {"anomaly": 15, "cashflow": 10, "forecast": 8, "monte_carlo": 20}

    scored: list[dict[str, Any]] = []
    for alert in raw_alerts:
        score = _LEVEL_SCORE.get(alert.level, 10)
        score += _SOURCE_BONUS.get(alert.source, 0)
        scored.append({
            "level": alert.level,
            "message": alert.message,
            "source": alert.source,
            "domain": alert.domain,
            "score": score,
            "action": _suggest_action(alert),
        })

    # Sort by score descending, take top N
    scored.sort(key=lambda x: -x["score"])
    top = scored[:limit]

    return {
        "data": {
            "top_alerts": top,
            "total_raw": len(raw_alerts),
            "has_critical": any(a["level"] == "critical" for a in top),
        },
        "error": None,
    }


def _suggest_action(alert: RawAlert) -> str:
    """Generate a short actionable suggestion for an alert."""
    source = alert.source
    level = alert.level
    if source == "cashflow" and level == "critical":
        return "Nakit çıkışlarını inceleyin ve giderleri önceliklendirin."
    if source == "cashflow":
        return "Nakit akışı sayfasını inceleyin."
    if source == "forecast":
        return "Tahmin senaryolarını gözden geçirin."
    if source == "anomaly":
        return "Anomaliler sayfasında işlemi doğrulayın."
    if source == "monte_carlo":
        return "Nakit ömrü riskini değerlendirin, bütçeyi gözden geçirin."
    if level == "critical":
        return "Acil müdahale gerekiyor — ilgili sayfayı inceleyin."
    return "Detaylar için analiz sayfasını inceleyin."


@router.post("/alerts/acknowledge/{job_id}/{alert_fingerprint}")
async def acknowledge_alert(
    job_id: str,
    alert_fingerprint: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    job: AnalysisJob = Depends(owned_job),
) -> dict[str, Any]:
    """
    Mark an alert as acknowledged.
    The fingerprint comes from RawAlert.fingerprint (12-char hex).

    Currently stores acknowledgement in Redis with 24h TTL.
    If Redis is unavailable, returns 200 with a warning.
    """
    try:
        import json

        from app.worker import get_arq_pool

        pool = await get_arq_pool()
        ack_key = f"ack:{job_id}:{alert_fingerprint}"
        await pool.set(
            ack_key,
            json.dumps({
                "job_id": job_id,
                "fingerprint": alert_fingerprint,
                "acknowledged_at": datetime.now(UTC).isoformat(),
            }),
            ex=86400,  # 24h
        )
        ack_stored = True
    except Exception as exc:
        logger.warning("Could not store acknowledgement in Redis: %s", exc)
        ack_stored = False

    return {
        "data": {
            "job_id": job_id,
            "fingerprint": alert_fingerprint,
            "acknowledged": True,
            "stored_in_redis": ack_stored,
        },
        "error": None,
    }
