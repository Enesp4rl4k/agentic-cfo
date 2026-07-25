"""
CHRO Attrition Agent

Analyzes employee turnover, churn rates, attrition by level/department, and replacement costs.
Pure calculation — no LLM required.
"""

import csv
from io import StringIO
from datetime import datetime
from typing import Any
from collections import Counter

from app.agents.chro.state import CHROState, CHROStepLog


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


def _parse_attrition_csv(csv_text: str) -> list[dict[str, Any]]:
    """Parse attrition/departure CSV — flexible column detection."""
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
    level_col = _col("level", "seniority", "grade")
    dept_col = _col("department", "dept", "team")
    departure_col = _col("departure_date", "exit_date", "last_day", "date")
    tenure_col = _col("tenure", "tenure_months", "months", "years_employed")
    reason_col = _col("reason", "departure_reason", "attrition_reason", "cause")
    replaced_col = _col("replaced", "replacement_hired", "backfilled")
    
    rows = []
    for i, row in enumerate(reader, start=1):
        try:
            name = (row.get(name_col) or f"Employee {i}").strip()
            level = (row.get(level_col) or "mid").strip().lower()
            dept = (row.get(dept_col) or "unknown").strip()
            reason = (row.get(reason_col) or "voluntary").strip().lower()
            
            # Departure date
            departure_date = None
            if departure_col and row.get(departure_col):
                departure_date = _parse_datetime(row.get(departure_col))
            
            # Tenure
            tenure_months = 0
            if tenure_col and row.get(tenure_col):
                try:
                    tenure_str = str(row.get(tenure_col)).replace(",", "").strip()
                    tenure_months = int(float(tenure_str))
                except (ValueError, TypeError):
                    tenure_months = 0
            
            # Replaced
            replaced = False
            if replaced_col and row.get(replaced_col):
                replaced_str = str(row.get(replaced_col)).strip().lower()
                replaced = replaced_str in ["yes", "true", "1", "replaced", "backfilled"]
            
            rows.append({
                "name": name,
                "level": level,
                "department": dept,
                "departure_date": departure_date,
                "tenure_months": tenure_months,
                "reason": reason,
                "replaced": replaced,
            })
        except Exception:
            pass
    
    return rows


def _compute_attrition_metrics(departures: list[dict[str, Any]]) -> dict[str, Any]:
    """Pure calculation — no LLM."""
    
    total_departures = len(departures)
    
    # By level
    by_level = Counter(d["level"] for d in departures)
    
    # By department
    by_dept = Counter(d["department"] for d in departures)
    
    # Churn reasons
    reasons = Counter(d["reason"] for d in departures)
    top_reasons = reasons.most_common(3)
    
    # Tenure analysis
    tenures = [d["tenure_months"] for d in departures if d["tenure_months"] > 0]
    avg_tenure_months = int(sum(tenures) / len(tenures)) if tenures else 0
    
    # Early departures (< 6 months)
    early_departures = [d for d in departures if d["tenure_months"] < 6]
    early_departure_rate = len(early_departures) / total_departures if total_departures > 0 else 0
    
    # Replaced rate
    replaced_count = len([d for d in departures if d["replaced"]])
    replaced_rate = replaced_count / total_departures if total_departures > 0 else 0
    
    # Recent departures (last 90 days — estimated)
    # Assuming data is recent; count last third as recent
    recent_threshold = max(1, total_departures // 3)
    recent_departures = departures[:recent_threshold]
    
    # Involuntary departures
    involuntary = [d for d in departures if d["reason"] in ["termination", "fired", "involuntary", "layoff"]]
    involuntary_rate = len(involuntary) / total_departures if total_departures > 0 else 0
    
    # Cost estimation (rough)
    # Assuming avg replacement cost = 6-9 months salary for mid-level
    replacement_cost_estimate = total_departures * 75_000 * 100  # $75k avg in cents
    
    return {
        "total_departures": total_departures,
        "by_level": dict(by_level),
        "by_department": dict(by_dept),
        "avg_tenure_months": avg_tenure_months,
        "early_departure_rate": round(early_departure_rate, 3),
        "early_departures_count": len(early_departures),
        "replaced_rate": round(replaced_rate, 3),
        "replaced_count": replaced_count,
        "involuntary_rate": round(involuntary_rate, 3),
        "involuntary_departures_count": len(involuntary),
        "attrition_reasons": dict(top_reasons),
        "recent_departures_count": len(recent_departures),
        "estimated_replacement_cost": replacement_cost_estimate,
    }


def _build_attrition_alerts(metrics: dict[str, Any]) -> list[dict[str, str]]:
    """Generate alerts based on attrition metrics."""
    alerts = []
    
    # High early departure rate
    if metrics.get("early_departure_rate", 0) > 0.20:
        alerts.append({
            "level": "critical",
            "message": f"High early departures: {metrics['early_departure_rate']*100:.0f}% leave within 6 months — investigate onboarding"
        })
    
    # Unbalanced replacement coverage
    if metrics.get("replaced_rate", 0) < 0.5 and metrics.get("total_departures", 0) > 5:
        alerts.append({
            "level": "warning",
            "message": f"Only {metrics['replaced_rate']*100:.0f}% of departures replaced — hiring gap detected"
        })
    
    # High involuntary departures
    if metrics.get("involuntary_rate", 0) > 0.15:
        alerts.append({
            "level": "warning",
            "message": f"High involuntary departures: {metrics['involuntary_rate']*100:.0f}% — review management & culture"
        })
    
    # High attrition cost
    cost = metrics.get("estimated_replacement_cost", 0)
    if cost > 1_000_000 * 100:  # > $1M
        cost_millions = cost / 100 / 1_000_000
        alerts.append({
            "level": "warning",
            "message": f"Estimated replacement cost: ${cost_millions:.1f}M — consider retention programs"
        })
    
    return alerts


async def _generate_attrition_narrative(
    metrics: dict[str, Any],
    settings,
    survival_result: dict[str, Any] | None = None,
) -> str:
    """Türkçe CHRO narrative — survival analysis bağlamıyla."""
    # Survival context
    survival_context = ""
    if survival_result and survival_result.get("summary"):
        s = survival_result["summary"]
        survival_context = (
            f"\nSurvival analizi: yıllık ayrılma %{s.get('annual_attrition_pct', 0):.0f}, "
            f"12 aylık tutunma %{s.get('survival_at_12m_pct', 0):.0f}, "
            f"kritik risk: {s.get('critical_risk_count', 0)} kişi"
        )
        if survival_result.get("high_risk_cohorts"):
            top = survival_result["high_risk_cohorts"][0]
            survival_context += (
                f", en riskli grup: '{top['department']}' / '{top['level']}'"
            )

    total      = metrics.get("total_departures", 0)
    tenure     = metrics.get("avg_tenure_months", 0)
    early_rate = metrics.get("early_departure_rate", 0)

    try:
        from app.config import get_settings as _gs
        settings = _gs()
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import HumanMessage, SystemMessage

        llm = ChatOpenAI(
            model=settings.llm_model,
            temperature=0.2,
            max_tokens=600,
            api_key=settings.openai_api_key,
            base_url=settings.llm_base_url or None,
        )

        response = await llm.ainvoke([
            SystemMessage(content=(
                "Sen deneyimli bir CHRO'sun. İşten ayrılma verilerini ve survival analizini "
                "inceleyerek Türkçe kısa, eyleme dönüştürülebilir bir özet yaz.\n"
                "Yapı:\n"
                "1. Attrition durumunun 1-2 cümlelik özeti\n"
                "2. En kritik grup/dönem\n"
                "3. İK ekibinin hemen yapması gereken 2-3 somut eylem\n"
                "Rakamları Türkçe birimlerle kullan."
            )),
            HumanMessage(content=(
                f"Toplam ayrılma: {total} | Ort. kıdem: {tenure:.0f} ay | "
                f"Erken ayrılma: %{early_rate*100:.0f}"
                + survival_context
            )),
        ])
        return response.content.strip()
    except Exception:
        pass

    # Fallback rule-based narrative
    narrative_lines = [
        f"Toplam {total} işten ayrılma analiz edildi. Ortalama kıdem: {tenure:.0f} ay."
    ]

    if early_rate > 0:
        narrative_lines.append(
            f"Erken ayrılma (<6 ay): ayrılmaların %{early_rate*100:.0f}'i."
        )
    
    if involuntary > 0:
        narrative_lines.append(
            f"Involuntary departures: {involuntary} terminations/layoffs."
        )
    
    return " ".join(narrative_lines)


async def run_attrition_agent(state: CHROState, config: dict) -> dict[str, Any]:
    """
    Attrition Skill Agent.
    done_when: state['attrition']['total_departures'] is an integer
    """
    
    result = {
        "attrition": None,
        "logs": state.get("logs") or [],
        "error": None,
    }
    
    try:
        csv_text = state.get("attrition_csv") or ""
        rows = _parse_attrition_csv(csv_text)
        metrics = _compute_attrition_metrics(rows)
        alerts  = _build_attrition_alerts(metrics)

        # ── Survival analysis ─────────────────────────────────────────────────
        survival_result: dict[str, Any] | None = None
        try:
            from app.agents.chro.survival import SurvivalAnalyzer

            # Current employees from headcount state (if available)
            current_employees = []
            hc = state.get("headcount") or {}
            if hc.get("employees"):
                current_employees = hc["employees"]

            if rows or current_employees:
                analyzer = SurvivalAnalyzer(
                    employees=current_employees,
                    departures=rows,
                )
                survival_result = analyzer.compute_full_analysis()
        except Exception as surv_exc:
            logger.warning("Survival analysis failed: %s", surv_exc)

        narrative = await _generate_attrition_narrative(
            metrics, config.get("settings"), survival_result=survival_result
        )

        result["attrition"] = {
            **metrics,
            "alerts":           alerts,
            "narrative":        narrative,
            "survival_analysis": survival_result,
        }
        
        log = CHROStepLog(
            node="attrition_agent",
            status="completed",
            message=f"Analyzed {len(rows)} departures",
            metrics={"total_departures": metrics["total_departures"]},
        )
        result["logs"].append(log)
        
    except Exception as e:
        result["error"] = f"Attrition agent failed: {str(e)}"
        log = CHROStepLog(
            node="attrition_agent",
            status="failed",
            message=str(e),
        )
        result["logs"].append(log)
    
    return result
