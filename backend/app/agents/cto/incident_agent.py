"""
Incident Agent — CTO Skill 3 of 5.

Responsibility: Analyze incident history to compute reliability metrics.

Computes:
- Total incident count and severity breakdown
- MTTR (Mean Time To Recover) in hours
- MTTD (Mean Time To Detect) in hours
- SLA breach count
- Recurring services (most incident-prone)
- Trend: improving / stable / degrading

Input: incident_csv — PagerDuty / OpsGenie / custom CSV export with columns:
  id, title, severity, service, started_at, resolved_at, [detected_at]

done_when: state['incidents']['mttr_hours'] is a float.
"""
from __future__ import annotations

import csv
import io
import logging
import re
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from app.agents.cto.state import CTOState, CTORunConfig, CTOSkillResult

logger = logging.getLogger(__name__)

SLA_TARGETS_HOURS = {
    "critical": 1.0,
    "high":     4.0,
    "medium":   24.0,
    "low":      72.0,
}


def _parse_datetime(raw: str) -> datetime | None:
    if not raw:
        return None
    raw = raw.strip()
    formats = [
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _parse_incident_csv(csv_text: str) -> list[dict[str, Any]]:
    """Parse incident CSV — flexible column detection."""
    rows = []
    reader = csv.DictReader(io.StringIO(csv_text.strip()))
    if not reader.fieldnames:
        return rows

    fields_lower = {f.lower().strip(): f for f in (reader.fieldnames or [])}

    def _col(*candidates: str) -> str | None:
        for c in candidates:
            if c.lower() in fields_lower:
                return fields_lower[c.lower()]
        return None

    id_col        = _col("id", "incident_id", "number")
    title_col     = _col("title", "name", "description", "summary")
    severity_col  = _col("severity", "priority", "urgency", "level")
    service_col   = _col("service", "affected_service", "component", "team")
    started_col   = _col("started_at", "created_at", "opened_at", "start_time", "timestamp")
    resolved_col  = _col("resolved_at", "closed_at", "end_time", "resolved")
    detected_col  = _col("detected_at", "acknowledged_at", "first_ack")

    for row in reader:
        inc_id    = row.get(id_col, "") if id_col else ""
        title     = row.get(title_col, "Unnamed incident") if title_col else "Unnamed incident"
        severity  = (row.get(severity_col, "medium") if severity_col else "medium").lower().strip()
        service   = (row.get(service_col, "unknown") if service_col else "unknown").strip()
        started   = _parse_datetime(row.get(started_col, "") if started_col else "")
        resolved  = _parse_datetime(row.get(resolved_col, "") if resolved_col else "")
        detected  = _parse_datetime(row.get(detected_col, "") if detected_col else "")

        if not started:
            continue

        # Normalize severity — keep standard values, map aliases
        if severity in ("critical", "p1", "sev1", "s1", "1"):
            severity = "critical"
        elif severity in ("high", "p2", "sev2", "s2", "2"):
            severity = "high"
        elif severity in ("medium", "p3", "sev3", "s3", "3", "moderate", "med"):
            severity = "medium"
        elif severity in ("low", "p4", "sev4", "s4", "4", "minor"):
            severity = "low"
        else:
            severity = "medium"

        # TTR in hours
        ttr_hours: float | None = None
        if resolved and started:
            delta = (resolved - started).total_seconds() / 3600
            ttr_hours = round(delta, 2) if delta >= 0 else None

        # TTD in hours (detection lag)
        ttd_hours: float | None = None
        if detected and started:
            delta = (detected - started).total_seconds() / 3600
            ttd_hours = round(max(0, delta), 2)

        # SLA breach
        sla_target = SLA_TARGETS_HOURS.get(severity, 24.0)
        sla_breached = ttr_hours is not None and ttr_hours > sla_target

        rows.append({
            "id": inc_id,
            "title": title,
            "severity": severity,
            "service": service,
            "started_at": started.isoformat(),
            "month": started.strftime("%Y-%m"),
            "ttr_hours": ttr_hours,
            "ttd_hours": ttd_hours,
            "sla_breached": sla_breached,
        })

    return rows


def _compute_incident_metrics(incidents: list[dict[str, Any]]) -> dict[str, Any]:
    """Pure calculation."""
    if not incidents:
        return {}

    by_severity: dict[str, int] = defaultdict(int)
    for inc in incidents:
        by_severity[inc["severity"]] += 1

    ttr_values = [i["ttr_hours"] for i in incidents if i["ttr_hours"] is not None]
    ttd_values = [i["ttd_hours"] for i in incidents if i["ttd_hours"] is not None]

    mttr = round(statistics.mean(ttr_values), 2) if ttr_values else None
    mttd = round(statistics.mean(ttd_values), 2) if ttd_values else None
    sla_breach_count = sum(1 for i in incidents if i["sla_breached"])

    # Recurring services
    service_counts: dict[str, int] = defaultdict(int)
    for inc in incidents:
        service_counts[inc["service"]] += 1
    total = len(incidents)
    recurring_services = sorted(
        [
            {"service": svc, "count": cnt, "pct": round(cnt / total * 100, 1)}
            for svc, cnt in service_counts.items()
        ],
        key=lambda x: x["count"],
        reverse=True,
    )[:5]

    # Trend: compare first half vs second half
    months = sorted(set(i["month"] for i in incidents))
    trend = "stable"
    if len(months) >= 4:
        mid = len(months) // 2
        first_half_months = set(months[:mid])
        second_half_months = set(months[mid:])
        first_count = sum(1 for i in incidents if i["month"] in first_half_months)
        second_count = sum(1 for i in incidents if i["month"] in second_half_months)
        if first_count > 0:
            change = (second_count - first_count) / first_count
            if change < -0.15:
                trend = "improving"
            elif change > 0.15:
                trend = "degrading"

    return {
        "total_incidents": total,
        "by_severity": dict(by_severity),
        "mttr_hours": mttr,
        "mttd_hours": mttd,
        "sla_breach_count": sla_breach_count,
        "sla_breach_pct": round(sla_breach_count / total * 100, 1) if total else 0,
        "recurring_services": recurring_services,
        "trend": trend,
        "months_analyzed": len(months),
    }


def _build_incident_alerts(metrics: dict[str, Any]) -> list[dict[str, str]]:
    alerts = []
    mttr = metrics.get("mttr_hours")
    if mttr is not None and mttr > 4:
        level = "critical" if mttr > 8 else "warning"
        alerts.append({
            "level": level,
            "message": f"Mean time to recover is {mttr:.1f}h — target is <4h for production incidents.",
        })

    breach_pct = metrics.get("sla_breach_pct", 0)
    if breach_pct > 20:
        alerts.append({
            "level": "critical" if breach_pct > 40 else "warning",
            "message": f"{breach_pct:.0f}% of incidents breached SLA targets. Reliability at risk.",
        })

    critical_count = metrics.get("by_severity", {}).get("critical", 0)
    if critical_count > 5:
        alerts.append({
            "level": "warning",
            "message": f"{critical_count} critical incidents in period. Review root causes for systemic issues.",
        })

    if metrics.get("trend") == "degrading":
        alerts.append({
            "level": "warning",
            "message": "Incident frequency is increasing — reliability is degrading over time.",
        })

    return alerts


async def _generate_incident_narrative(
    metrics: dict[str, Any],
    alerts: list[dict[str, str]],
    settings,
) -> str:
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import HumanMessage, SystemMessage

    llm = ChatOpenAI(
        model=settings.llm_model,
        temperature=0.2,
        max_tokens=512,
        api_key=settings.openai_api_key,
        base_url=settings.llm_base_url or None,
    )

    by_sev = metrics.get("by_severity", {})
    alert_text = (
        "\n".join(f"- [{a['level'].upper()}] {a['message']}" for a in alerts)
        or "No critical alerts."
    )
    top_services = "\n".join(
        f"  - {s['service']}: {s['count']} incidents ({s['pct']}%)"
        for s in metrics.get("recurring_services", [])[:3]
    ) or "  No data"

    messages = [
        SystemMessage(content=(
            "Sen deneyimli bir CTO'sun, güvenilirlik mühendisliği konusunda uzmansın. "
            "Aşağıdaki olay (incident) verilerini analiz et ve Türkçe olarak kısa, eyleme dönüştürülebilir bir özet yaz. "
            "Yanıt şu yapıda olsun:\n"
            "1. Mevcut güvenilirlik durumunun 1-2 cümlelik değerlendirmesi (MTTR, SLA ihlali odaklı)\n"
            "2. En kritik 1-2 sorun ve kök neden kalıbı\n"
            "3. Ekibin hemen yapması gereken 2-3 somut teknik eylem (madde madde)\n"
            "Teknik jargonu azalt, yöneticinin anlayacağı dilde yaz."
        )),
        HumanMessage(content=(
            f"Toplam Olay: {metrics['total_incidents']}\n"
            f"Önem Dağılımı: kritik={by_sev.get('critical',0)}, yüksek={by_sev.get('high',0)}, "
            f"orta={by_sev.get('medium',0)}, düşük={by_sev.get('low',0)}\n"
            f"MTTR: {metrics.get('mttr_hours', 'N/A')}s | MTTD: {metrics.get('mttd_hours', 'N/A')}s\n"
            f"SLA İhlali: {metrics['sla_breach_count']} adet ({metrics['sla_breach_pct']}%)\n"
            f"Trend: {metrics['trend']}\n\n"
            f"En Çok Olay Yaşanan Servisler:\n{top_services}\n\n"
            f"Uyarılar:\n{alert_text}"
        )),
    ]
    response = await llm.ainvoke(messages)
    return response.content.strip()


async def run_incident_agent(
    state: CTOState,
    config: CTORunConfig,
) -> CTOSkillResult:
    """
    IncidentAgent Skill.
    done_when: state['incidents']['mttr_hours'] is a float.
    """
    incident_csv = state.get("incident_csv")
    if not incident_csv:
        return CTOSkillResult(
            ok=True,
            patch={"incidents": None},
            confidence=1.0,
            detail="No incident data provided — IncidentAgent skipped.",
        )

    try:
        from app.config import get_settings
        settings = get_settings()

        incidents = _parse_incident_csv(incident_csv)
        if not incidents:
            return CTOSkillResult(
                ok=False,
                detail="Could not parse incident CSV — no valid rows found.",
                confidence=0.3,
                needs_review=True,
            )

        metrics = _compute_incident_metrics(incidents)
        alerts = _build_incident_alerts(metrics)
        narrative = await _generate_incident_narrative(metrics, alerts, settings)

        metrics["alerts"] = alerts
        metrics["narrative"] = narrative

        has_critical = any(a["level"] == "critical" for a in alerts)
        confidence = 0.92 if not has_critical else 0.82

        logger.info(
            "IncidentAgent: job=%s total=%d mttr=%.1fh sla_breach=%d trend=%s",
            state.get("job_id"),
            metrics["total_incidents"],
            metrics.get("mttr_hours") or 0,
            metrics["sla_breach_count"],
            metrics["trend"],
        )

        return CTOSkillResult(
            ok=True,
            patch={"incidents": metrics},
            confidence=confidence,
            needs_review=has_critical,
            detail=(
                f"Incidents: {metrics['total_incidents']}, "
                f"MTTR: {metrics.get('mttr_hours', 'N/A')}h, "
                f"SLA breaches: {metrics['sla_breach_count']}, "
                f"trend: {metrics['trend']}"
            ),
        )

    except Exception as exc:
        logger.exception("IncidentAgent failed for job=%s", state.get("job_id"))
        return CTOSkillResult(ok=False, detail=f"IncidentAgent error: {exc}")
