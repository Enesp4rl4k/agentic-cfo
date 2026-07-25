"""
CHRO Headcount Agent

Analyzes organizational structure, FTE counts, hiring/promotion trends, and staffing risks.
Pure calculation — no LLM required.
"""

import csv
from io import StringIO
from datetime import datetime
from typing import Any

from app.agents.chro.state import CHROState, CHROStepLog


def _parse_headcount_csv(csv_text: str) -> list[dict[str, Any]]:
    """Parse headcount CSV — flexible column detection."""
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
    
    name_col = _col("name", "employee", "employee_name")
    level_col = _col("level", "seniority", "grade", "rank")
    dept_col = _col("department", "dept", "team", "function")
    role_col = _col("role", "title", "job_title", "position")
    salary_col = _col("salary", "base_salary", "compensation", "base")
    location_col = _col("location", "office", "city", "region")
    start_col = _col("start_date", "hire_date", "joined")
    status_col = _col("status", "employment_status", "state")
    
    rows = []
    for i, row in enumerate(reader, start=1):
        try:
            name = (row.get(name_col) or f"Employee {i}").strip()
            level = (row.get(level_col) or "mid").strip().lower()
            dept = (row.get(dept_col) or "unknown").strip()
            role = (row.get(role_col) or "").strip()
            status = (row.get(status_col) or "active").strip().lower()
            location = (row.get(location_col) or "").strip()
            
            # Salary in cents
            salary = 0
            if salary_col and row.get(salary_col):
                try:
                    sal_str = str(row.get(salary_col)).replace(",", "").strip()
                    salary = int(float(sal_str) * 100)
                except (ValueError, TypeError):
                    salary = 0
            
            # Start date
            start_date = None
            if start_col and row.get(start_col):
                try:
                    start_date = datetime.strptime(
                        str(row.get(start_col)).strip(), "%Y-%m-%d"
                    ).date()
                except (ValueError, TypeError):
                    start_date = None
            
            rows.append({
                "name": name,
                "level": level,
                "department": dept,
                "role": role,
                "salary": salary,
                "location": location,
                "start_date": start_date,
                "status": status,
            })
        except Exception:
            pass
    
    return rows


def _compute_headcount_metrics(employees: list[dict[str, Any]]) -> dict[str, Any]:
    """Pure calculation — no LLM."""
    
    active = [e for e in employees if e["status"] == "active"]
    total_headcount = len(active)
    
    # By level
    by_level = {}
    for e in active:
        level = e["level"]
        if level not in by_level:
            by_level[level] = 0
        by_level[level] += 1
    
    # By department
    by_dept = {}
    for e in active:
        dept = e["department"]
        if dept not in by_dept:
            by_dept[dept] = 0
        by_dept[dept] += 1
    
    # Salary metrics
    active_salaries = [e["salary"] for e in active if e["salary"] > 0]
    total_annual_payroll = sum(active_salaries)  # in cents
    avg_salary = int(total_annual_payroll / len(active_salaries)) if active_salaries else 0
    
    # Tenure analysis
    today = datetime.now().date()
    tenures = []
    for e in active:
        if e["start_date"]:
            tenure_days = (today - e["start_date"]).days
            tenures.append(tenure_days)
    
    avg_tenure_days = int(sum(tenures) / len(tenures)) if tenures else 0
    avg_tenure_years = avg_tenure_days / 365.25
    
    # Recently hired (< 1 year)
    recently_hired = [
        e for e in active
        if e["start_date"] and (today - e["start_date"]).days < 365
    ]
    
    # High salary roles (top 10% by comp)
    if active_salaries:
        threshold = sorted(active_salaries)[-max(1, len(active_salaries) // 10)]
        high_earners = [e for e in active if e["salary"] >= threshold]
    else:
        high_earners = []
    
    # Org structure risk: unbalanced levels
    level_ratios = {
        level: count / total_headcount
        for level, count in by_level.items()
    }
    
    # Healthy pyramid: exec ~5%, senior ~15%, mid ~40%, junior ~40%
    org_health_risk = False
    if len(by_level) < 2:
        org_health_risk = True  # Flat org
    
    return {
        "total_headcount": total_headcount,
        "by_level": by_level,
        "by_department": by_dept,
        "total_annual_payroll": total_annual_payroll,
        "avg_salary": avg_salary,
        "avg_tenure_years": round(avg_tenure_years, 2),
        "recently_hired_count": len(recently_hired),
        "high_earners_count": len(high_earners),
        "org_structure_risk": org_health_risk,
        "level_distribution": level_ratios,
    }


def _build_headcount_alerts(metrics: dict[str, Any]) -> list[dict[str, str]]:
    """Generate alerts based on headcount metrics."""
    alerts = []
    
    # Org structure risk
    if metrics.get("org_structure_risk"):
        alerts.append({
            "level": "warning",
            "message": "Org structure imbalanced — consider building management layers"
        })
    
    # High recent hiring (potential onboarding burden)
    if metrics.get("recently_hired_count", 0) > metrics.get("total_headcount", 1) * 0.15:
        alerts.append({
            "level": "info",
            "message": f"High recent hiring ({metrics['recently_hired_count']} in <1yr) — focus on onboarding & retention"
        })
    
    # High concentration of salary
    if metrics.get("high_earners_count", 0) > metrics.get("total_headcount", 1) * 0.15:
        alerts.append({
            "level": "warning",
            "message": f"High earner concentration — {metrics['high_earners_count']} in top 10% comp"
        })
    
    return alerts


async def _generate_headcount_narrative(
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
    hc = metrics.get("total_headcount", 0)
    tenure = metrics.get("avg_tenure_years", 0)
    recent = metrics.get("recently_hired_count", 0)
    payroll = metrics.get("total_annual_payroll", 0)
    
    narrative_lines = [
        f"Organization has {hc} active employees with average tenure of {tenure:.1f} years.",
    ]
    
    if recent > 0:
        narrative_lines.append(
            f"Recent hiring activity: {recent} employees hired in last 12 months."
        )
    
    if payroll > 0:
        payroll_millions = payroll / 100 / 1_000_000
        narrative_lines.append(
            f"Annual payroll commitment: ${payroll_millions:.1f}M"
        )
    
    return " ".join(narrative_lines)


async def run_headcount_agent(state: CHROState, config: dict) -> dict[str, Any]:
    """
    Headcount Skill Agent.
    done_when: state['headcount']['total_headcount'] is an integer
    """
    
    result = {
        "headcount": None,
        "logs": state.get("logs") or [],
        "error": None,
    }
    
    try:
        csv_text = state.get("headcount_csv") or ""
        rows = _parse_headcount_csv(csv_text)
        metrics = _compute_headcount_metrics(rows)
        alerts = _build_headcount_alerts(metrics)
        narrative = await _generate_headcount_narrative(metrics, config.get("settings"))
        
        result["headcount"] = {
            **metrics,
            "alerts": alerts,
            "narrative": narrative,
        }
        
        log = CHROStepLog(
            node="headcount_agent",
            status="completed",
            message=f"Analyzed {len(rows)} employees",
            metrics={"total_headcount": metrics["total_headcount"]},
        )
        result["logs"].append(log)
        
    except Exception as e:
        result["error"] = f"Headcount agent failed: {str(e)}"
        log = CHROStepLog(
            node="headcount_agent",
            status="failed",
            message=str(e),
        )
        result["logs"].append(log)
    
    return result
