"""
Compliance Policies Agent

Analyzes policy inventory, tracking status, compliance coverage, and policy age.
Pure calculation — no LLM required.
"""

import csv
from io import StringIO
from datetime import datetime, timedelta
from typing import Any
from collections import Counter

from app.agents.compliance.state import ComplianceState, ComplianceStepLog


def _parse_datetime(raw: str) -> datetime | None:
    """Parse datetime flexibly."""
    if not raw:
        return None
    try:
        for fmt in ["%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S"]:
            try:
                return datetime.strptime(raw.strip(), fmt)
            except ValueError:
                continue
    except Exception:
        pass
    return None


def _parse_policies_csv(csv_text: str) -> list[dict[str, Any]]:
    """Parse policies CSV — flexible column detection."""
    if not csv_text or not csv_text.strip():
        return []
    
    lines = csv_text.strip().split("\n")
    if not lines:
        return []
    
    reader = csv.DictReader(lines)
    if not reader.fieldnames:
        return []
    
    def _col(*candidates: str) -> str | None:
        """Find first matching column name (case-insensitive)."""
        candidates_lower = [c.lower() for c in candidates]
        for field in reader.fieldnames or []:
            if field.lower() in candidates_lower:
                return field
        return None
    
    name_col = _col("policy", "policy_name", "name")
    severity_col = _col("severity", "level", "criticality")
    status_col = _col("status", "state")
    review_col = _col("last_review", "last_reviewed", "review_date")
    owner_col = _col("owner", "responsible", "owner_name")
    category_col = _col("category", "type", "domain")
    
    rows = []
    for i, row in enumerate(reader, start=1):
        try:
            name = (row.get(name_col) or f"Policy {i}").strip()
            severity = (row.get(severity_col) or "medium").strip().lower()
            status = (row.get(status_col) or "active").strip().lower()
            owner = (row.get(owner_col) or "unknown").strip()
            category = (row.get(category_col) or "governance").strip()
            
            # Last review date
            review_date = None
            if review_col and row.get(review_col):
                review_date = _parse_datetime(row.get(review_col))
            
            rows.append({
                "name": name,
                "severity": severity,
                "status": status,
                "owner": owner,
                "category": category,
                "last_review_date": review_date,
            })
        except Exception:
            pass
    
    return rows


def _compute_policies_metrics(policies: list[dict[str, Any]]) -> dict[str, Any]:
    """Pure calculation — no LLM."""
    
    total_policies = len(policies)
    
    # By status
    by_status = Counter(p["status"] for p in policies)
    
    # By severity
    by_severity = Counter(p["severity"] for p in policies)
    
    # By category
    by_category = Counter(p["category"] for p in policies)
    
    # By owner
    by_owner = Counter(p["owner"] for p in policies)
    
    # Policies needing review (> 1 year old)
    today = datetime.now()
    one_year_ago = today - timedelta(days=365)
    
    needs_review = []
    for p in policies:
        if p["last_review_date"] and p["last_review_date"] < one_year_ago:
            days_overdue = (today - p["last_review_date"]).days
            needs_review.append({
                "policy": p["name"],
                "days_overdue": days_overdue,
            })
    
    # Critical/high policies
    critical = [p for p in policies if p["severity"] in ["critical", "high"]]
    
    # Active/current policies
    active = [p for p in policies if p["status"] == "active"]
    
    # Policy coverage (avg critical policies per owner)
    if by_owner:
        avg_per_owner = total_policies / len(by_owner)
    else:
        avg_per_owner = 0
    
    return {
        "total_policies": total_policies,
        "by_status": dict(by_status),
        "by_severity": dict(by_severity),
        "by_category": dict(by_category),
        "by_owner": dict(by_owner),
        "active_policies": len(active),
        "critical_policies": len(critical),
        "policies_needing_review": len(needs_review),
        "avg_policies_per_owner": round(avg_per_owner, 1),
        "review_overdue": needs_review[:5],  # Top 5 overdue
    }


def _build_policies_alerts(metrics: dict[str, Any]) -> list[dict[str, str]]:
    """Generate alerts based on policy metrics."""
    alerts = []
    
    # Policies needing review
    overdue_count = metrics.get("policies_needing_review", 0)
    if overdue_count > 0:
        alerts.append({
            "level": "warning",
            "message": f"{overdue_count} policies haven't been reviewed in >1 year — schedule reviews"
        })
    
    # High concentration of policies on one owner
    by_owner = metrics.get("by_owner", {})
    if by_owner:
        max_owner_count = max(by_owner.values()) if by_owner else 0
        if max_owner_count > metrics.get("total_policies", 1) * 0.40:
            alerts.append({
                "level": "medium",
                "message": f"Policy ownership concentrated — one owner manages {max_owner_count} of {metrics['total_policies']} policies"
            })
    
    # Many critical policies
    if metrics.get("critical_policies", 0) > metrics.get("total_policies", 1) * 0.25:
        alerts.append({
            "level": "info",
            "message": f"High proportion of critical policies ({metrics['critical_policies']}/{metrics['total_policies']})"
        })
    
    # No active policies
    if metrics.get("active_policies", 0) == 0:
        alerts.append({
            "level": "critical",
            "message": "No active policies — governance framework incomplete"
        })
    
    return alerts


async def _generate_policies_narrative(
    metrics: dict[str, Any], settings
) -> str:
    """Optional LLM narrative — falls back to rule-based summary."""
    try:
        if settings and hasattr(settings, "llm") and settings.llm:
            from app.config import get_settings
            settings = get_settings()
            if not settings.openai_key:
                raise ValueError("No OpenAI key")
            # LLM call would go here (optional)
            pass
    except Exception:
        pass
    
    # Fallback rule-based narrative
    total = metrics.get("total_policies", 0)
    active = metrics.get("active_policies", 0)
    critical = metrics.get("critical_policies", 0)
    overdue = metrics.get("policies_needing_review", 0)
    
    narrative_lines = [
        f"Policy inventory: {total} policies ({active} active)."
    ]
    
    if critical > 0:
        narrative_lines.append(
            f"Critical/high severity policies: {critical}"
        )
    
    if overdue > 0:
        narrative_lines.append(
            f"Policies needing review: {overdue} overdue by >1 year."
        )
    
    return " ".join(narrative_lines)


async def run_policies_agent(state: ComplianceState, config: dict) -> dict[str, Any]:
    """
    Policies Skill Agent.
    done_when: state['policies']['total_policies'] is an integer
    """
    
    result = {
        "policies": None,
        "logs": state.get("logs") or [],
        "error": None,
    }
    
    try:
        csv_text = state.get("policy_csv") or ""
        rows = _parse_policies_csv(csv_text)
        metrics = _compute_policies_metrics(rows)
        alerts = _build_policies_alerts(metrics)
        narrative = await _generate_policies_narrative(metrics, config.get("settings"))
        
        result["policies"] = {
            **metrics,
            "alerts": alerts,
            "narrative": narrative,
        }
        
        log = ComplianceStepLog(
            node="policies_agent",
            status="completed",
            message=f"Analyzed {len(rows)} policies",
            metrics={"total_policies": metrics["total_policies"]},
        )
        result["logs"].append(log)
        
    except Exception as e:
        result["error"] = f"Policies agent failed: {str(e)}"
        log = ComplianceStepLog(
            node="policies_agent",
            status="failed",
            message=str(e),
        )
        result["logs"].append(log)
    
    return result
