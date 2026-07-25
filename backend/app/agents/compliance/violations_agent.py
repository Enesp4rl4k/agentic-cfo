"""
Compliance Violations Agent — Skill 2 of 3.

Tracks corporate violations: open incidents, remediation status,
overdue items, and SLA breach patterns.

Input: violations_csv
  Columns: violation, policy_id, severity, date_found, due_date,
           remediation_status, responsible_party, [framework]

done_when: state['violations']['total_violations'] is an int.
"""
from __future__ import annotations

import csv
import io
import logging
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from app.agents.compliance.state import ComplianceState, ComplianceStepLog

logger = logging.getLogger(__name__)

# Days overdue thresholds by severity
OVERDUE_SLA_DAYS: dict[str, int] = {
    "critical": 7,
    "high":     30,
    "medium":   90,
    "low":      180,
}

# Remediation status normalisation map
OPEN_STATUSES = {"open", "new", "identified", "in progress", "pending", "investigating"}
CLOSED_STATUSES = {"closed", "resolved", "remediated", "fixed", "accepted", "mitigated"}


def _parse_datetime(raw: str) -> datetime | None:
    if not raw or not raw.strip():
        return None
    for fmt in ["%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"]:
        try:
            return datetime.strptime(raw.strip(), fmt)
        except ValueError:
            continue
    return None


def _norm_severity(raw: str) -> str:
    s = raw.lower().strip()
    if s in ("critical", "crit", "p1", "sev1"):
        return "critical"
    if s in ("high", "p2", "sev2"):
        return "high"
    if s in ("medium", "med", "p3", "sev3", "moderate"):
        return "medium"
    return "low"


def _norm_status(raw: str) -> str:
    s = raw.lower().strip()
    if s in CLOSED_STATUSES:
        return "closed"
    return "open"


def _parse_violations_csv(csv_text: str) -> list[dict[str, Any]]:
    """Parse violations CSV — flexible column detection."""
    if not csv_text or not csv_text.strip():
        return []

    reader = csv.DictReader(io.StringIO(csv_text.strip()))
    if not reader.fieldnames:
        return []

    fields_lower = {f.lower().strip(): f for f in (reader.fieldnames or [])}

    def _col(*candidates: str) -> str | None:
        for c in candidates:
            if c.lower() in fields_lower:
                return fields_lower[c.lower()]
        return None

    viol_col      = _col("violation", "title", "name", "description", "finding")
    policy_col    = _col("policy_id", "policy", "policy_ref", "control")
    severity_col  = _col("severity", "level", "priority", "criticality")
    found_col     = _col("date_found", "found_date", "created_at", "discovered_at", "date")
    due_col       = _col("due_date", "remediation_due", "target_date", "deadline")
    status_col    = _col("remediation_status", "status", "state")
    owner_col     = _col("responsible_party", "owner", "assignee", "responsible")
    framework_col = _col("framework", "regulation", "standard", "source")

    rows: list[dict[str, Any]] = []
    today = datetime.now()

    for i, row in enumerate(reader, start=1):
        try:
            violation   = (row.get(viol_col) or f"Violation {i}").strip() if viol_col else f"Violation {i}"
            policy_id   = (row.get(policy_col) or "unknown").strip() if policy_col else "unknown"
            severity    = _norm_severity(row.get(severity_col, "medium") if severity_col else "medium")
            status_raw  = (row.get(status_col, "open") if status_col else "open")
            status      = _norm_status(status_raw)
            owner       = (row.get(owner_col, "unassigned") if owner_col else "unassigned").strip()
            framework   = (row.get(framework_col, "internal") if framework_col else "internal").strip()

            date_found  = _parse_datetime(row.get(found_col, "") if found_col else "")
            due_date    = _parse_datetime(row.get(due_col, "") if due_col else "")

            # Compute days open / overdue
            days_open: int | None = None
            if date_found:
                days_open = (today - date_found).days

            overdue: bool = False
            days_overdue: int = 0
            if status == "open":
                if due_date and due_date < today:
                    days_overdue = (today - due_date).days
                    overdue = True
                elif date_found:
                    # No explicit due date → use SLA threshold
                    sla_days = OVERDUE_SLA_DAYS.get(severity, 90)
                    if days_open is not None and days_open > sla_days:
                        days_overdue = days_open - sla_days
                        overdue = True

            rows.append({
                "violation": violation,
                "policy_id": policy_id,
                "severity": severity,
                "status": status,
                "owner": owner,
                "framework": framework,
                "date_found": date_found.isoformat() if date_found else None,
                "due_date": due_date.isoformat() if due_date else None,
                "days_open": days_open,
                "overdue": overdue,
                "days_overdue": days_overdue,
            })
        except Exception:
            logger.debug("Skipping violation row %d due to parse error", i)

    return rows


def _compute_violations_metrics(violations: list[dict[str, Any]]) -> dict[str, Any]:
    """Pure calculation — no LLM."""
    if not violations:
        return {
            "total_violations": 0,
            "open_violations": 0,
            "closed_violations": 0,
            "overdue_violations": 0,
            "critical_open": 0,
            "by_severity": {},
            "by_status": {},
            "by_framework": {},
            "by_owner": {},
            "remediation_rate": 0.0,
            "overdue_rate": 0.0,
            "avg_days_open": None,
            "top_overdue": [],
            "top_owners_by_open": [],
        }

    total  = len(violations)
    open_v = [v for v in violations if v["status"] == "open"]
    closed = [v for v in violations if v["status"] == "closed"]
    overdue = [v for v in violations if v["overdue"]]

    by_severity  = dict(Counter(v["severity"] for v in violations))
    by_status    = dict(Counter(v["status"]   for v in violations))
    by_framework = dict(Counter(v["framework"] for v in violations))
    by_owner     = dict(Counter(v["owner"]     for v in violations))

    critical_open = sum(
        1 for v in open_v if v["severity"] == "critical"
    )

    remediation_rate = round(len(closed) / total * 100, 1) if total else 0.0
    overdue_rate     = round(len(overdue) / len(open_v) * 100, 1) if open_v else 0.0

    # Average days open (only for items with date_found)
    days_values = [v["days_open"] for v in open_v if v["days_open"] is not None]
    avg_days_open = round(sum(days_values) / len(days_values), 1) if days_values else None

    # Top overdue violations (sorted by severity then days_overdue)
    sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    top_overdue = sorted(
        [v for v in violations if v["overdue"]],
        key=lambda x: (sev_order.get(x["severity"], 3), -x["days_overdue"]),
    )[:8]

    # Top owners by open count
    open_by_owner: dict[str, int] = defaultdict(int)
    for v in open_v:
        open_by_owner[v["owner"]] += 1
    top_owners = sorted(
        [{"owner": o, "open_count": c} for o, c in open_by_owner.items()],
        key=lambda x: x["open_count"],
        reverse=True,
    )[:5]

    return {
        "total_violations": total,
        "open_violations": len(open_v),
        "closed_violations": len(closed),
        "overdue_violations": len(overdue),
        "critical_open": critical_open,
        "by_severity": by_severity,
        "by_status": by_status,
        "by_framework": by_framework,
        "by_owner": by_owner,
        "remediation_rate": remediation_rate,
        "overdue_rate": overdue_rate,
        "avg_days_open": avg_days_open,
        "top_overdue": [
            {
                "violation": v["violation"],
                "severity": v["severity"],
                "owner": v["owner"],
                "days_overdue": v["days_overdue"],
                "framework": v["framework"],
            }
            for v in top_overdue
        ],
        "top_owners_by_open": top_owners,
    }


def _build_violations_alerts(metrics: dict[str, Any]) -> list[dict[str, str]]:
    """Generate actionable alerts from violation metrics."""
    alerts: list[dict[str, str]] = []

    critical_open = metrics.get("critical_open", 0)
    if critical_open > 0:
        alerts.append({
            "level": "critical",
            "message": (
                f"{critical_open} critical violation(s) still open — "
                "require immediate remediation within 7 days."
            ),
        })

    overdue = metrics.get("overdue_violations", 0)
    overdue_rate = metrics.get("overdue_rate", 0.0)
    if overdue > 0:
        level = "critical" if overdue_rate > 50 else "warning"
        alerts.append({
            "level": level,
            "message": (
                f"{overdue} violation(s) overdue ({overdue_rate:.0f}% of open items). "
                "Escalate to owners and set firm deadlines."
            ),
        })

    remediation_rate = metrics.get("remediation_rate", 0.0)
    total = metrics.get("total_violations", 0)
    if total > 0 and remediation_rate < 50:
        alerts.append({
            "level": "warning",
            "message": (
                f"Remediation rate only {remediation_rate:.0f}% — "
                "more than half of violations remain open."
            ),
        })

    avg_days = metrics.get("avg_days_open")
    if avg_days is not None and avg_days > 60:
        level = "critical" if avg_days > 120 else "warning"
        alerts.append({
            "level": level,
            "message": (
                f"Average time to remediate is {avg_days:.0f} days — "
                "violations are ageing without resolution."
            ),
        })

    # Ownership concentration
    by_owner = metrics.get("by_owner", {})
    if by_owner:
        max_count = max(by_owner.values())
        if total and max_count > total * 0.40:
            top_owner = max(by_owner, key=by_owner.get)  # type: ignore[arg-type]
            alerts.append({
                "level": "info",
                "message": (
                    f"Violation ownership concentrated: '{top_owner}' owns "
                    f"{max_count}/{total} items — consider redistributing."
                ),
            })

    return alerts


def _build_remediation_recommendations(
    metrics: dict[str, Any],
) -> list[dict[str, str]]:
    """Generate concrete, actionable remediation recommendations."""
    recs: list[dict[str, str]] = []

    if metrics.get("critical_open", 0) > 0:
        recs.append({
            "priority": "P1",
            "action": "Immediate remediation of all critical violations",
            "detail": (
                "Assign a dedicated owner, set a 7-day hard deadline, "
                "and schedule daily stand-ups until resolved."
            ),
            "effort": "high",
        })

    top_overdue = metrics.get("top_overdue", [])
    if top_overdue:
        most_overdue = top_overdue[0]
        recs.append({
            "priority": "P2",
            "action": f"Escalate overdue violation: '{most_overdue['violation']}'",
            "detail": (
                f"This {most_overdue['severity']} violation is {most_overdue['days_overdue']} days overdue. "
                f"Owner: {most_overdue['owner']}. Escalate to management if unresolved by end of week."
            ),
            "effort": "medium",
        })

    if metrics.get("remediation_rate", 100) < 60:
        recs.append({
            "priority": "P2",
            "action": "Establish weekly violation review cadence",
            "detail": (
                "With <60% remediation rate, implement weekly compliance review meetings "
                "to track progress and remove blockers."
            ),
            "effort": "low",
        })

    top_owners = metrics.get("top_owners_by_open", [])
    if top_owners and top_owners[0]["open_count"] > 3:
        recs.append({
            "priority": "P3",
            "action": f"Redistribute workload from '{top_owners[0]['owner']}'",
            "detail": (
                f"'{top_owners[0]['owner']}' has {top_owners[0]['open_count']} open violations. "
                "Redistribute to reduce remediation bottleneck."
            ),
            "effort": "low",
        })

    by_framework = metrics.get("by_framework", {})
    if by_framework:
        top_framework = max(by_framework, key=by_framework.get)  # type: ignore[arg-type]
        recs.append({
            "priority": "P3",
            "action": f"Focused review of {top_framework} compliance",
            "detail": (
                f"{by_framework[top_framework]} violations linked to {top_framework}. "
                "Run a targeted control assessment for this framework."
            ),
            "effort": "medium",
        })

    return recs


async def run_violations_agent(
    state: ComplianceState,
    config: dict,
) -> dict[str, Any]:
    """
    Violations Skill Agent.
    done_when: state['violations']['total_violations'] is an int.
    """
    result: dict[str, Any] = {
        "violations": None,
        "logs": list(state.get("logs") or []),
        "error": None,
    }

    try:
        csv_text = state.get("violations_csv") or ""
        rows     = _parse_violations_csv(csv_text)
        metrics  = _compute_violations_metrics(rows)
        alerts   = _build_violations_alerts(metrics)
        recs     = _build_remediation_recommendations(metrics)

        # Build narrative
        total        = metrics["total_violations"]
        open_count   = metrics["open_violations"]
        critical     = metrics["critical_open"]
        overdue      = metrics["overdue_violations"]
        rem_rate     = metrics["remediation_rate"]

        if total == 0:
            narrative = "No violations data provided — violation tracking not available."
        else:
            parts = [
                f"Violations: {total} total ({open_count} open, {metrics['closed_violations']} closed).",
                f"Remediation rate: {rem_rate:.0f}%.",
            ]
            if critical > 0:
                parts.append(f"CRITICAL: {critical} open critical violation(s) require immediate action.")
            if overdue > 0:
                parts.append(f"{overdue} violation(s) are overdue.")
            narrative = " ".join(parts)

        result["violations"] = {
            **metrics,
            "alerts": alerts,
            "recommendations": recs,
            "narrative": narrative,
        }

        log = ComplianceStepLog(
            node="violations_agent",
            status="completed",
            message=f"Analyzed {len(rows)} violations ({metrics['open_violations']} open)",
            metrics={
                "total": metrics["total_violations"],
                "open": metrics["open_violations"],
                "critical_open": metrics["critical_open"],
                "overdue": metrics["overdue_violations"],
            },
        )
        result["logs"].append(log)

        logger.info(
            "ViolationsAgent: total=%d open=%d critical=%d overdue=%d",
            total, open_count, critical, overdue,
        )

    except Exception as exc:
        logger.exception("ViolationsAgent failed")
        result["error"] = f"Violations agent failed: {exc}"
        result["logs"].append(ComplianceStepLog(
            node="violations_agent",
            status="failed",
            message=str(exc),
        ))

    return result
