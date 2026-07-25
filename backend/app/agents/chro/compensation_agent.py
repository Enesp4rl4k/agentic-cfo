"""
CHRO Compensation Agent

Analyzes salary bands, equity allocation, benefits costs, market alignment, and equity burn.
Pure calculation — no LLM required.
"""

import csv
from io import StringIO
from datetime import datetime
from typing import Any
from collections import Counter

from app.agents.chro.state import CHROState, CHROStepLog


def _parse_compensation_csv(csv_text: str) -> list[dict[str, Any]]:
    """Parse compensation CSV — flexible column detection."""
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
    salary_col = _col("salary", "base_salary", "base")
    bonus_col = _col("bonus", "bonus_percentage", "target_bonus")
    equity_col = _col("equity_shares", "equity", "stock_options", "option_grant", "options")
    equity_vesting_col = _col("vesting", "vest_date", "vesting_schedule")
    benefits_col = _col("benefits", "benefits_cost", "benefits_package")
    market_salary_col = _col("market_salary", "market_rate", "industry_rate")
    
    rows = []
    for i, row in enumerate(reader, start=1):
        try:
            name = (row.get(name_col) or f"Employee {i}").strip()
            level = (row.get(level_col) or "mid").strip().lower()
            dept = (row.get(dept_col) or "unknown").strip()
            
            # Salary in cents
            salary = 0
            if salary_col and row.get(salary_col):
                try:
                    sal_str = str(row.get(salary_col)).replace(",", "").strip()
                    salary = int(float(sal_str) * 100)
                except (ValueError, TypeError):
                    salary = 0
            
            # Bonus as percentage
            bonus_pct = 0
            if bonus_col and row.get(bonus_col):
                try:
                    bonus_str = str(row.get(bonus_col)).replace("%", "").strip()
                    bonus_pct = float(bonus_str) / 100
                except (ValueError, TypeError):
                    bonus_pct = 0
            
            # Equity in shares/options
            equity_shares = 0
            if equity_col and row.get(equity_col):
                try:
                    equity_str = str(row.get(equity_col)).replace(",", "").strip()
                    equity_shares = int(float(equity_str))
                except (ValueError, TypeError):
                    equity_shares = 0
            
            # Vesting info
            vesting_info = (row.get(equity_vesting_col) or "4-year").strip()
            
            # Benefits cost in cents
            benefits = 0
            if benefits_col and row.get(benefits_col):
                try:
                    ben_str = str(row.get(benefits_col)).replace(",", "").strip()
                    benefits = int(float(ben_str) * 100)
                except (ValueError, TypeError):
                    benefits = 0
            
            # Market salary in cents
            market_salary = 0
            if market_salary_col and row.get(market_salary_col):
                try:
                    mkt_str = str(row.get(market_salary_col)).replace(",", "").strip()
                    market_salary = int(float(mkt_str) * 100)
                except (ValueError, TypeError):
                    market_salary = 0
            
            rows.append({
                "name": name,
                "level": level,
                "department": dept,
                "salary": salary,
                "bonus_pct": bonus_pct,
                "equity_shares": equity_shares,
                "vesting": vesting_info,
                "benefits": benefits,
                "market_salary": market_salary,
            })
        except Exception:
            pass
    
    return rows


def _compute_compensation_metrics(employees: list[dict[str, Any]]) -> dict[str, Any]:
    """Pure calculation — no LLM."""
    
    total_employees = len(employees)
    
    # Salary metrics by level
    by_level = {}
    for e in employees:
        level = e["level"]
        if level not in by_level:
            by_level[level] = []
        by_level[level].append(e["salary"])
    
    avg_salary_by_level = {
        level: int(sum(sals) / len(sals)) if sals else 0
        for level, sals in by_level.items()
    }
    
    # Total comp costs (salary + benefits)
    total_salary = sum(e["salary"] for e in employees)
    total_benefits = sum(e["benefits"] for e in employees)
    total_annual_comp = total_salary + total_benefits
    
    # Bonus pool
    total_bonus_pool = sum(int(e["salary"] * e["bonus_pct"]) for e in employees)
    
    # Equity analysis
    total_equity_shares = sum(e["equity_shares"] for e in employees)
    employees_with_equity = len([e for e in employees if e["equity_shares"] > 0])
    equity_penetration = employees_with_equity / total_employees if total_employees > 0 else 0
    
    # Market alignment
    below_market = 0
    above_market = 0
    for e in employees:
        if e["market_salary"] > 0:
            if e["salary"] < e["market_salary"] * 0.90:
                below_market += 1
            elif e["salary"] > e["market_salary"] * 1.10:
                above_market += 1
    
    # Salary compression risk (ratio of highest to lowest in same level)
    compression_ratios = {}
    for level, sals in by_level.items():
        if len(sals) > 1:
            min_sal = min(sals)
            max_sal = max(sals)
            if min_sal > 0:
                ratio = max_sal / min_sal
                compression_ratios[level] = ratio
    
    # Equity burn (annual dilution at 4-year vest)
    annual_equity_burn = int(total_equity_shares / 4)
    
    return {
        "total_employees": total_employees,
        "avg_salary_by_level": avg_salary_by_level,
        "total_annual_salary": total_salary,
        "total_annual_benefits": total_benefits,
        "total_annual_comp": total_annual_comp,
        "total_bonus_pool": total_bonus_pool,
        "total_equity_shares": total_equity_shares,
        "employees_with_equity": employees_with_equity,
        "equity_penetration": round(equity_penetration, 3),
        "annual_equity_burn": annual_equity_burn,
        "below_market_count": below_market,
        "above_market_count": above_market,
        "salary_compression_ratios": compression_ratios,
    }


def _build_compensation_alerts(metrics: dict[str, Any]) -> list[dict[str, str]]:
    """Generate alerts based on compensation metrics."""
    alerts = []
    
    # Wide salary compression
    for level, ratio in metrics.get("salary_compression_ratios", {}).items():
        if ratio > 1.5:
            alerts.append({
                "level": "warning",
                "message": f"Salary compression risk in {level} level: {ratio:.1f}x spread between min/max"
            })
    
    # Many below market
    below_count = metrics.get("below_market_count", 0)
    if below_count > metrics.get("total_employees", 1) * 0.20:
        alerts.append({
            "level": "warning",
            "message": f"{below_count} employees ({below_count/metrics['total_employees']*100:.0f}%) paid below market — retention risk"
        })
    
    # Low equity penetration
    equity_pen = metrics.get("equity_penetration", 0)
    if equity_pen < 0.50 and metrics.get("total_employees", 0) > 5:
        alerts.append({
            "level": "info",
            "message": f"Low equity penetration ({equity_pen*100:.0f}%) — consider broader equity program"
        })
    
    # High equity burn
    burn = metrics.get("annual_equity_burn", 0)
    if burn > 100_000:
        alerts.append({
            "level": "warning",
            "message": f"High annual equity burn: {burn:,} shares/year — review cap table impact"
        })
    
    return alerts


async def _generate_compensation_narrative(
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
    total_comp = metrics.get("total_annual_comp", 0)
    equity_pen = metrics.get("equity_penetration", 0)
    burn = metrics.get("annual_equity_burn", 0)
    
    narrative_lines = []
    
    if total_comp > 0:
        total_comp_millions = total_comp / 100 / 1_000_000
        narrative_lines.append(
            f"Total annual compensation commitment: ${total_comp_millions:.1f}M"
        )
    
    narrative_lines.append(
        f"Equity penetration: {equity_pen*100:.0f}% of workforce has equity grants."
    )
    
    if burn > 0:
        narrative_lines.append(
            f"Annual equity burn rate: {burn:,} shares at 4-year vest schedule."
        )
    
    return " ".join(narrative_lines)


async def run_compensation_agent(state: CHROState, config: dict) -> dict[str, Any]:
    """
    Compensation Skill Agent.
    done_when: state['compensation']['total_annual_comp'] is an integer
    """
    
    result = {
        "compensation": None,
        "logs": state.get("logs") or [],
        "error": None,
    }
    
    try:
        csv_text = state.get("compensation_csv") or ""
        rows = _parse_compensation_csv(csv_text)
        metrics = _compute_compensation_metrics(rows)
        alerts = _build_compensation_alerts(metrics)
        narrative = await _generate_compensation_narrative(metrics, config.get("settings"))
        
        result["compensation"] = {
            **metrics,
            "alerts": alerts,
            "narrative": narrative,
        }
        
        log = CHROStepLog(
            node="compensation_agent",
            status="completed",
            message=f"Analyzed compensation for {len(rows)} employees",
            metrics={"total_annual_comp": metrics["total_annual_comp"]},
        )
        result["logs"].append(log)
        
    except Exception as e:
        result["error"] = f"Compensation agent failed: {str(e)}"
        log = CHROStepLog(
            node="compensation_agent",
            status="failed",
            message=str(e),
        )
        result["logs"].append(log)
    
    return result
