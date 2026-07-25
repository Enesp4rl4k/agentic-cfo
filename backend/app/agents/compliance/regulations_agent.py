"""
Compliance Regulations Agent — Skill 3 of 3.

Tracks regulatory requirements: SOC2, ISO 27001, GDPR, HIPAA, PCI-DSS, etc.
Measures compliance coverage, audit readiness, and control effectiveness.

Input: regulations_csv
  Columns: regulation, requirement, compliance_status, last_audit,
           next_audit, control_owner, [evidence_status], [risk_level]

done_when: state['regulations']['total_requirements'] is an int.
"""
from __future__ import annotations

import csv
import io
import logging
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any

from app.agents.compliance.state import ComplianceState, ComplianceStepLog

logger = logging.getLogger(__name__)

# Recognised compliance frameworks
KNOWN_FRAMEWORKS = {
    "soc2", "soc 2", "soc2 type ii", "soc 2 type ii",
    "iso27001", "iso 27001", "iso 27001:2013", "iso 27001:2022",
    "gdpr", "hipaa", "pci-dss", "pci dss",
    "nist", "nist csf", "nist 800-53",
    "ccpa", "fedramp", "cmmc",
    "sox", "sarbanes-oxley",
    "cis", "cis controls",
}

COMPLIANT_STATUSES = {
    "compliant", "met", "satisfied", "implemented", "yes", "pass", "passed", "full",
}
NON_COMPLIANT_STATUSES = {
    "non-compliant", "non_compliant", "not met", "not implemented", "fail", "failed",
    "no", "missing", "gap",
}
PARTIAL_STATUSES = {
    "partial", "in progress", "partially met", "partially implemented",
    "pending", "remediation in progress",
}


def _parse_datetime(raw: str) -> datetime | None:
    if not raw or not raw.strip():
        return None
    for fmt in ["%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S"]:
        try:
            return datetime.strptime(raw.strip(), fmt)
        except ValueError:
            continue
    return None


def _norm_compliance_status(raw: str) -> str:
    s = raw.lower().strip()
    if s in COMPLIANT_STATUSES:
        return "compliant"
    if s in NON_COMPLIANT_STATUSES:
        return "non_compliant"
    if s in PARTIAL_STATUSES:
        return "partial"
    return "unknown"


def _norm_risk(raw: str) -> str:
    s = raw.lower().strip()
    if s in ("critical", "crit", "p1"):
        return "critical"
    if s in ("high", "p2"):
        return "high"
    if s in ("medium", "med", "moderate", "p3"):
        return "medium"
    return "low"


def _parse_regulations_csv(csv_text: str) -> list[dict[str, Any]]:
    """Parse regulations CSV — flexible column detection."""
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

    reg_col        = _col("regulation", "framework", "standard", "source")
    req_col        = _col("requirement", "control", "control_id", "requirement_id", "item")
    status_col     = _col("compliance_status", "status", "compliance", "state")
    last_audit_col = _col("last_audit", "last_audit_date", "audited_at", "audit_date")
    next_audit_col = _col("next_audit", "next_audit_date", "review_date")
    owner_col      = _col("control_owner", "owner", "responsible", "assignee")
    evidence_col   = _col("evidence_status", "evidence", "documentation")
    risk_col       = _col("risk_level", "risk", "severity", "impact")

    rows: list[dict[str, Any]] = []
    today = datetime.now()

    for i, row in enumerate(reader, start=1):
        try:
            regulation  = (row.get(reg_col) or "Unknown").strip() if reg_col else "Unknown"
            requirement = (row.get(req_col) or f"Requirement {i}").strip() if req_col else f"Requirement {i}"
            status_raw  = (row.get(status_col, "unknown") if status_col else "unknown")
            status      = _norm_compliance_status(status_raw)
            owner       = (row.get(owner_col, "unassigned") if owner_col else "unassigned").strip()
            evidence    = (row.get(evidence_col, "unknown") if evidence_col else "unknown").strip().lower()
            risk        = _norm_risk(row.get(risk_col, "medium") if risk_col else "medium")

            last_audit = _parse_datetime(row.get(last_audit_col, "") if last_audit_col else "")
            next_audit = _parse_datetime(row.get(next_audit_col, "") if next_audit_col else "")

            # Days since last audit
            days_since_audit: int | None = None
            if last_audit:
                days_since_audit = (today - last_audit).days

            # Audit overdue check (> 12 months)
            audit_overdue = (
                last_audit is not None and days_since_audit is not None and days_since_audit > 365
            ) or (last_audit is None)

            # Next audit upcoming check (within 30 days)
            audit_due_soon = (
                next_audit is not None and 0 <= (next_audit - today).days <= 30
            )

            rows.append({
                "regulation": regulation,
                "requirement": requirement,
                "status": status,
                "owner": owner,
                "evidence": evidence,
                "risk": risk,
                "last_audit": last_audit.isoformat() if last_audit else None,
                "next_audit": next_audit.isoformat() if next_audit else None,
                "days_since_audit": days_since_audit,
                "audit_overdue": audit_overdue,
                "audit_due_soon": audit_due_soon,
            })
        except Exception:
            logger.debug("Skipping regulation row %d", i)

    return rows


def _compute_regulations_metrics(reqs: list[dict[str, Any]]) -> dict[str, Any]:
    """Pure calculation — no LLM."""
    if not reqs:
        return {
            "total_requirements": 0,
            "compliant_count": 0,
            "non_compliant_count": 0,
            "partial_count": 0,
            "unknown_count": 0,
            "compliance_coverage_pct": 0.0,
            "frameworks": [],
            "by_framework": {},
            "by_risk": {},
            "audit_overdue_count": 0,
            "audit_due_soon_count": 0,
            "gaps": [],
            "framework_scores": {},
        }

    total        = len(reqs)
    compliant    = [r for r in reqs if r["status"] == "compliant"]
    non_compliant = [r for r in reqs if r["status"] == "non_compliant"]
    partial      = [r for r in reqs if r["status"] == "partial"]
    unknown      = [r for r in reqs if r["status"] == "unknown"]

    # Coverage: compliant + partial (partial counts as 0.5)
    effective_compliant = len(compliant) + len(partial) * 0.5
    coverage_pct = round(effective_compliant / total * 100, 1) if total else 0.0

    # By framework
    frameworks_seen = sorted(set(r["regulation"] for r in reqs))
    by_framework: dict[str, dict[str, int]] = {}
    for fw in frameworks_seen:
        fw_reqs = [r for r in reqs if r["regulation"] == fw]
        by_framework[fw] = {
            "total": len(fw_reqs),
            "compliant": sum(1 for r in fw_reqs if r["status"] == "compliant"),
            "non_compliant": sum(1 for r in fw_reqs if r["status"] == "non_compliant"),
            "partial": sum(1 for r in fw_reqs if r["status"] == "partial"),
        }

    # Framework scores (0–100)
    framework_scores: dict[str, float] = {}
    for fw, counts in by_framework.items():
        fw_total = counts["total"]
        if fw_total:
            eff = counts["compliant"] + counts["partial"] * 0.5
            framework_scores[fw] = round(eff / fw_total * 100, 1)
        else:
            framework_scores[fw] = 0.0

    by_risk = dict(Counter(r["risk"] for r in reqs))
    audit_overdue_count = sum(1 for r in reqs if r["audit_overdue"])
    audit_due_soon_count = sum(1 for r in reqs if r["audit_due_soon"])

    # Top gaps: non-compliant requirements sorted by risk
    risk_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    gaps = sorted(
        non_compliant + partial,
        key=lambda x: (risk_order.get(x["risk"], 3), x["regulation"]),
    )[:10]

    return {
        "total_requirements": total,
        "compliant_count": len(compliant),
        "non_compliant_count": len(non_compliant),
        "partial_count": len(partial),
        "unknown_count": len(unknown),
        "compliance_coverage_pct": coverage_pct,
        "frameworks": frameworks_seen,
        "by_framework": by_framework,
        "by_risk": by_risk,
        "framework_scores": framework_scores,
        "audit_overdue_count": audit_overdue_count,
        "audit_due_soon_count": audit_due_soon_count,
        "gaps": [
            {
                "framework": g["regulation"],
                "requirement": g["requirement"],
                "status": g["status"],
                "risk": g["risk"],
                "owner": g["owner"],
            }
            for g in gaps
        ],
    }


def _build_regulations_alerts(metrics: dict[str, Any]) -> list[dict[str, str]]:
    """Generate actionable compliance alerts."""
    alerts: list[dict[str, str]] = []

    coverage = metrics.get("compliance_coverage_pct", 100.0)
    total    = metrics.get("total_requirements", 0)

    if total == 0:
        return alerts

    if coverage < 70:
        level = "critical" if coverage < 50 else "warning"
        alerts.append({
            "level": level,
            "message": (
                f"Compliance coverage only {coverage:.0f}% — "
                f"{metrics['non_compliant_count']} requirements non-compliant, "
                f"{metrics['partial_count']} partial. Immediate remediation required."
            ),
        })
    elif coverage < 85:
        alerts.append({
            "level": "warning",
            "message": (
                f"Compliance coverage {coverage:.0f}% — "
                f"below 85% target. Address {metrics['non_compliant_count']} gaps."
            ),
        })

    # Framework-specific alerts
    fw_scores = metrics.get("framework_scores", {})
    for fw, score in fw_scores.items():
        if score < 60:
            alerts.append({
                "level": "critical",
                "message": (
                    f"{fw} compliance score {score:.0f}% — critical gaps requiring urgent attention."
                ),
            })
        elif score < 80:
            alerts.append({
                "level": "warning",
                "message": f"{fw} compliance score {score:.0f}% — below acceptable threshold.",
            })

    # Audit overdue
    overdue_count = metrics.get("audit_overdue_count", 0)
    if overdue_count > 0:
        alerts.append({
            "level": "warning",
            "message": (
                f"{overdue_count} requirement(s) not audited in over 12 months — "
                "schedule audits to maintain evidence currency."
            ),
        })

    # Upcoming audits
    due_soon = metrics.get("audit_due_soon_count", 0)
    if due_soon > 0:
        alerts.append({
            "level": "info",
            "message": (
                f"{due_soon} audit(s) due within the next 30 days — "
                "ensure evidence packages are complete."
            ),
        })

    return alerts


def _build_compliance_recommendations(
    metrics: dict[str, Any],
) -> list[dict[str, str]]:
    """Actionable, framework-specific recommendations."""
    recs: list[dict[str, str]] = []

    gaps = metrics.get("gaps", [])
    critical_gaps = [g for g in gaps if g["risk"] == "critical"]

    if critical_gaps:
        recs.append({
            "priority": "P1",
            "action": f"Remediate {len(critical_gaps)} critical compliance gap(s) immediately",
            "detail": (
                f"Critical gaps: {', '.join(g['requirement'] for g in critical_gaps[:3])}. "
                "Assign dedicated owners and set 2-week hard deadlines."
            ),
            "effort": "high",
        })

    low_score_fw = [
        (fw, score)
        for fw, score in metrics.get("framework_scores", {}).items()
        if score < 75
    ]
    if low_score_fw:
        fw_name, score = low_score_fw[0]
        recs.append({
            "priority": "P2",
            "action": f"Launch {fw_name} remediation sprint",
            "detail": (
                f"{fw_name} score is {score:.0f}%. Run a focused 4-week remediation sprint. "
                "Use the framework's official control list to close each gap systematically."
            ),
            "effort": "high",
        })

    if metrics.get("audit_overdue_count", 0) > 0:
        recs.append({
            "priority": "P2",
            "action": "Schedule overdue compliance audits",
            "detail": (
                f"{metrics['audit_overdue_count']} requirement(s) need re-audit. "
                "Book audit dates now — stale evidence is a common reason for audit failures."
            ),
            "effort": "medium",
        })

    if metrics.get("partial_count", 0) > 3:
        recs.append({
            "priority": "P3",
            "action": "Convert partial compliance items to full compliance",
            "detail": (
                f"{metrics['partial_count']} requirements are partially met. "
                "Prioritise high-risk partials — they count as half in coverage scoring."
            ),
            "effort": "medium",
        })

    if metrics.get("compliance_coverage_pct", 100) >= 90:
        recs.append({
            "priority": "P4",
            "action": "Automate compliance evidence collection",
            "detail": (
                "With high coverage, the next maturity step is continuous compliance monitoring. "
                "Consider GRC tools (Vanta, Drata, Tugboat Logic) to automate evidence gathering."
            ),
            "effort": "medium",
        })

    return recs


async def run_regulations_agent(
    state: ComplianceState,
    config: dict,
) -> dict[str, Any]:
    """
    Regulations Skill Agent.
    done_when: state['regulations']['total_requirements'] is an int.
    """
    result: dict[str, Any] = {
        "regulations": None,
        "logs": list(state.get("logs") or []),
        "error": None,
    }

    try:
        csv_text = state.get("regulations_csv") or ""
        rows     = _parse_regulations_csv(csv_text)
        metrics  = _compute_regulations_metrics(rows)
        alerts   = _build_regulations_alerts(metrics)
        recs     = _build_compliance_recommendations(metrics)

        # Build narrative
        total    = metrics["total_requirements"]
        coverage = metrics["compliance_coverage_pct"]
        fws      = metrics["frameworks"]

        if total == 0:
            narrative = "No regulations data provided — regulatory tracking not available."
        else:
            fw_list = ", ".join(fws[:4]) + ("..." if len(fws) > 4 else "")
            parts = [
                f"Regulatory coverage: {coverage:.0f}% across {len(fws)} framework(s) ({fw_list}).",
                f"{metrics['compliant_count']} compliant, "
                f"{metrics['non_compliant_count']} non-compliant, "
                f"{metrics['partial_count']} partial.",
            ]
            if metrics["non_compliant_count"] > 0:
                parts.append(
                    f"Priority: address {metrics['non_compliant_count']} non-compliant requirement(s)."
                )
            narrative = " ".join(parts)

        result["regulations"] = {
            **metrics,
            "alerts": alerts,
            "recommendations": recs,
            "narrative": narrative,
        }

        log = ComplianceStepLog(
            node="regulations_agent",
            status="completed",
            message=(
                f"Analyzed {len(rows)} requirements across "
                f"{len(metrics['frameworks'])} framework(s), "
                f"coverage={coverage:.1f}%"
            ),
            metrics={
                "total_requirements": metrics["total_requirements"],
                "compliant": metrics["compliant_count"],
                "non_compliant": metrics["non_compliant_count"],
                "coverage_pct": coverage,
            },
        )
        result["logs"].append(log)

        logger.info(
            "RegulationsAgent: total=%d compliant=%d non_compliant=%d coverage=%.1f%%",
            total,
            metrics["compliant_count"],
            metrics["non_compliant_count"],
            coverage,
        )

    except Exception as exc:
        logger.exception("RegulationsAgent failed")
        result["error"] = f"Regulations agent failed: {exc}"
        result["logs"].append(ComplianceStepLog(
            node="regulations_agent",
            status="failed",
            message=str(exc),
        ))

    return result
