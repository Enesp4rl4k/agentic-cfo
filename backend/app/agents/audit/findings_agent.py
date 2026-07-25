"""
Audit Findings Agent

Tracks audit findings by severity, monitors overdue remediations, scores the
finding portfolio, and surfaces systemic repeat findings.
Pure calculation — no LLM required.
"""

from __future__ import annotations

import csv
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any

from app.agents.audit.state import AuditState, AuditStepLog


def _parse_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(str(raw).strip(), fmt)
        except ValueError:
            pass
    return None


def _parse_findings_csv(csv_text: str) -> list[dict[str, Any]]:
    if not csv_text or not csv_text.strip():
        return []
    lines = csv_text.strip().splitlines()
    reader = csv.DictReader(lines)
    if not reader.fieldnames:
        return []

    def _col(*candidates: str) -> str | None:
        low = {f.lower(): f for f in reader.fieldnames or []}
        for c in candidates:
            if c.lower() in low:
                return low[c.lower()]
        return None

    id_col        = _col("finding_id", "id", "ref")
    title_col     = _col("title", "finding", "description")
    severity_col  = _col("severity", "rating", "level")
    status_col    = _col("status", "remediation_status", "state")
    due_col       = _col("due_date", "remediation_due", "target_date")
    owner_col     = _col("owner", "responsible", "finding_owner")
    category_col  = _col("category", "type", "area")
    repeat_col    = _col("repeat", "repeat_finding", "is_repeat")

    rows: list[dict[str, Any]] = []
    today = datetime.now()

    for i, row in enumerate(reader, start=1):
        try:
            fid       = (row.get(id_col) or f"F{i:03d}").strip() if id_col else f"F{i:03d}"
            title     = (row.get(title_col) or f"Finding {i}").strip() if title_col else f"Finding {i}"
            severity  = (row.get(severity_col) or "medium").strip().lower() if severity_col else "medium"
            status    = (row.get(status_col) or "open").strip().lower() if status_col else "open"
            owner     = (row.get(owner_col) or "Unassigned").strip() if owner_col else "Unassigned"
            category  = (row.get(category_col) or "general").strip().lower() if category_col else "general"
            due_date  = _parse_date(row.get(due_col)) if due_col else None
            repeat_raw = str(row.get(repeat_col) or "").strip().lower() if repeat_col else ""
            is_repeat  = repeat_raw in ("yes", "true", "1", "y")

            # Normalise severity
            if severity not in ("critical", "high", "medium", "low", "informational"):
                severity = "medium"
            # Normalise status
            if status not in ("open", "closed", "in_progress", "accepted", "overdue"):
                status = "open"

            overdue = False
            days_overdue = 0
            if due_date and status in ("open", "in_progress"):
                days_overdue = (today - due_date).days
                overdue = days_overdue > 0

            rows.append({
                "id": fid, "title": title, "severity": severity,
                "status": status, "owner": owner, "category": category,
                "due_date": due_date, "is_repeat": is_repeat,
                "overdue": overdue, "days_overdue": days_overdue,
            })
        except Exception:
            pass
    return rows


def _compute_findings_metrics(findings: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(findings)
    if total == 0:
        return {
            "total_findings": 0,
            "by_severity": {}, "by_status": {}, "by_category": {},
            "open_critical": 0, "overdue_count": 0, "repeat_findings": 0,
            "remediation_rate": 0.0, "top_overdue": [], "finding_health_score": 0.0,
        }

    by_severity  = Counter(f["severity"] for f in findings)
    by_status    = Counter(f["status"] for f in findings)
    by_category  = Counter(f["category"] for f in findings)

    open_critical = sum(1 for f in findings
                        if f["severity"] == "critical" and f["status"] in ("open", "in_progress"))
    overdue       = [f for f in findings if f["overdue"]]
    repeat_count  = sum(1 for f in findings if f["is_repeat"])

    closed        = sum(1 for f in findings if f["status"] == "closed")
    remediation_rate = closed / total if total > 0 else 0.0

    top_overdue = sorted(overdue, key=lambda f: f["days_overdue"], reverse=True)[:5]

    # Finding health score 0-100 (higher = healthier)
    # Deductions: critical open (-15 each), overdue (-5 each), repeats (-3 each)
    score = 100.0
    score -= open_critical * 15
    score -= len(overdue) * 5
    score -= repeat_count * 3
    score = max(0.0, min(100.0, score))

    return {
        "total_findings":   total,
        "by_severity":      dict(by_severity),
        "by_status":        dict(by_status),
        "by_category":      dict(by_category),
        "open_critical":    open_critical,
        "overdue_count":    len(overdue),
        "repeat_findings":  repeat_count,
        "remediation_rate": round(remediation_rate, 3),
        "top_overdue": [
            {"id": f["id"], "title": f["title"], "severity": f["severity"],
             "days_overdue": f["days_overdue"], "owner": f["owner"]}
            for f in top_overdue
        ],
        "finding_health_score": round(score, 1),
    }


def _build_findings_alerts(metrics: dict[str, Any]) -> list[dict[str, str]]:
    alerts: list[dict[str, str]] = []

    if metrics.get("open_critical", 0):
        alerts.append({
            "level": "critical",
            "message": (
                f"{metrics['open_critical']} CRITICAL finding(s) still open — "
                "escalate to management and set immediate remediation deadline."
            ),
        })

    overdue = metrics.get("overdue_count", 0)
    if overdue:
        alerts.append({
            "level": "warning",
            "message": f"{overdue} finding(s) past remediation due date — risk of unresolved exposure.",
        })

    if metrics.get("repeat_findings", 0) > 2:
        alerts.append({
            "level": "warning",
            "message": (
                f"{metrics['repeat_findings']} repeat findings detected — "
                "root-cause remediation is inadequate."
            ),
        })

    if metrics.get("remediation_rate", 1.0) < 0.50:
        rate = metrics["remediation_rate"]
        alerts.append({
            "level": "info",
            "message": f"Remediation rate {rate:.0%} — majority of findings still open.",
        })

    return alerts


async def run_findings_agent(state: AuditState, config: dict) -> dict[str, Any]:
    logs: list[AuditStepLog] = list(state.get("logs") or [])
    result: dict[str, Any] = {"findings": None, "logs": logs, "error": None}
    try:
        rows    = _parse_findings_csv(state.get("findings_csv") or "")
        metrics = _compute_findings_metrics(rows)
        alerts  = _build_findings_alerts(metrics)
        result["findings"] = {
            **metrics, "alerts": alerts,
            "narrative": (
                f"{metrics['total_findings']} findings ({metrics['open_critical']} critical open); "
                f"remediation rate {metrics['remediation_rate']:.0%}; "
                f"health score {metrics['finding_health_score']}/100."
            ),
        }
        logs.append(AuditStepLog(
            node="findings_agent", status="completed",
            message=f"Processed {len(rows)} findings",
            metrics={"open_critical": metrics["open_critical"]},
        ))
    except Exception as exc:
        result["error"] = f"findings_agent failed: {exc}"
        logs.append(AuditStepLog(node="findings_agent", status="failed", message=str(exc)))
    return result
