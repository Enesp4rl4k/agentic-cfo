"""
COO Resource Agent -- COO Skill 2 of 3.

Responsibility: Parse headcount/resource CSV and compute utilization rates,
output per FTE, overutilization/burnout risk, and departmental efficiency.

Supported CSV formats (flexible column detection):
  - Generic: team/department, headcount/ftes, utilization/utilization_rate,
             output/tasks_completed, capacity/max_capacity, cost/labor_cost

done_when: state['resources']['avg_utilization_rate'] is a float
"""
from __future__ import annotations

import csv
import io
import logging
from typing import Any

from app.agents.coo.state import COOState

logger = logging.getLogger(__name__)


# -- CSV Parser ---------------------------------------------------------------

def _parse_resource_csv(csv_text: str) -> list[dict[str, Any]]:
    """Parse resource/headcount CSV -- flexible column detection."""
    reader = csv.DictReader(io.StringIO(csv_text.strip()))
    rows: list[dict[str, Any]] = []

    def _col(*candidates: str) -> str | None:
        for c in candidates:
            for k in (reader.fieldnames or []):
                if k.strip().lower().replace(" ", "_").replace("-", "_") == \
                   c.lower().replace(" ", "_"):
                    return k
        return None

    team_col        = _col("team", "department", "dept", "squad", "group", "name")
    headcount_col   = _col("headcount", "ftes", "fte", "employees", "count", "staff")
    util_col        = _col("utilization", "utilization_rate", "util_pct",
                           "capacity_used", "billable_rate")
    output_col      = _col("output", "tasks_completed", "deliverables",
                           "weekly_output", "monthly_output", "productivity")
    capacity_col    = _col("capacity", "max_capacity", "max_output", "target_output")
    cost_col        = _col("cost", "labor_cost", "monthly_cost", "salary_total")

    for i, row in enumerate(reader):
        team      = (row.get(team_col) or f"Team {i+1}").strip()
        headcount = 1
        util      = None
        output    = 0.0
        capacity  = 0.0
        cost      = 0.0

        try:
            headcount = max(1, int(float((row.get(headcount_col) or "1").replace(",", ""))))
        except (ValueError, TypeError):
            pass

        # Utilization: normalize to 0-1
        raw_util = (row.get(util_col) or "").strip().rstrip("%")
        try:
            val = float(raw_util.replace(",", ""))
            util = val / 100 if val > 1 else val
            util = min(1.5, max(0.0, util))  # allow up to 150% (overtime)
        except (ValueError, TypeError):
            pass

        try:
            output = float((row.get(output_col) or "0").replace(",", ""))
        except (ValueError, TypeError):
            pass
        try:
            capacity = float((row.get(capacity_col) or "0").replace(",", ""))
        except (ValueError, TypeError):
            pass
        try:
            cost = float((row.get(cost_col) or "0").replace(",", "").replace("$", ""))
        except (ValueError, TypeError):
            pass

        # If utilization not provided, infer from output/capacity
        if util is None and capacity > 0 and output > 0:
            util = min(1.5, output / capacity)
        elif util is None:
            util = 0.0

        rows.append({
            "team":        team,
            "headcount":   headcount,
            "utilization": util,
            "output":      output,
            "capacity":    capacity,
            "cost_cents":  int(cost * 100),
        })

    return rows


# -- Pure Calculations --------------------------------------------------------

def _compute_resource_metrics(
    resources: list[dict[str, Any]],
    total_revenue_cents: int = 0,
) -> dict[str, Any]:
    """Pure calculation -- no LLM."""
    if not resources:
        return {
            "total_headcount":       0,
            "avg_utilization_rate":  0.0,
            "revenue_per_fte_cents": 0,
            "output_per_fte":        0.0,
            "overutilized_teams":    [],
            "underutilized_teams":   [],
            "by_department":         {},
            "alerts":                [],
            "narrative":             "",
        }

    total_hc   = sum(r["headcount"] for r in resources)
    total_cost = sum(r["cost_cents"] for r in resources)

    # Weighted average utilization (weighted by headcount)
    weighted_util = sum(r["utilization"] * r["headcount"] for r in resources)
    avg_util = weighted_util / total_hc if total_hc > 0 else 0.0

    # Revenue per FTE
    rev_per_fte = total_revenue_cents // total_hc if total_hc > 0 else 0

    # Output per FTE (aggregate)
    total_output = sum(r["output"] for r in resources)
    output_per_fte = total_output / total_hc if total_hc > 0 else 0.0

    # -- By department --------------------------------------------------------
    by_dept: dict[str, Any] = {}
    for r in resources:
        cap = r["capacity"]
        out = r["output"]
        util = r["utilization"]
        by_dept[r["team"]] = {
            "headcount":    r["headcount"],
            "utilization":  round(util, 3),
            "output":       out,
            "capacity":     cap,
            "cost_cents":   r["cost_cents"],
            "output_per_fte": round(out / r["headcount"], 2) if r["headcount"] > 0 else 0.0,
        }

    # -- Over/under utilization -----------------------------------------------
    # > 90% = overutilized (burnout risk), < 50% = underutilized (waste)
    overutilized = [
        {
            "team":        r["team"],
            "utilization": r["utilization"],
            "headcount":   r["headcount"],
            "burnout_risk": "critical" if r["utilization"] > 1.1 else "high",
        }
        for r in resources if r["utilization"] > 0.90
    ]

    underutilized = [
        {
            "team":        r["team"],
            "utilization": r["utilization"],
            "headcount":   r["headcount"],
            "opportunity": "Reallocate or upskill to higher-demand areas",
        }
        for r in resources if 0 < r["utilization"] < 0.50
    ]

    return {
        "total_headcount":        total_hc,
        "total_cost_cents":       total_cost,
        "avg_utilization_rate":   round(avg_util, 3),
        "revenue_per_fte_cents":  rev_per_fte,
        "output_per_fte":         round(output_per_fte, 2),
        "overutilized_teams":     sorted(overutilized, key=lambda x: -x["utilization"]),
        "underutilized_teams":    sorted(underutilized, key=lambda x: x["utilization"]),
        "by_department":          by_dept,
        "alerts":                 [],
        "narrative":              "",
    }


def _build_resource_alerts(metrics: dict[str, Any]) -> list[dict[str, str]]:
    """Generate actionable alerts from resource metrics."""
    alerts: list[dict[str, str]] = []

    util     = metrics.get("avg_utilization_rate", 0.0)
    over     = metrics.get("overutilized_teams", [])
    under    = metrics.get("underutilized_teams", [])
    rev_fte  = metrics.get("revenue_per_fte_cents", 0)
    hc       = metrics.get("total_headcount", 0)

    if util > 1.0:
        alerts.append({
            "level": "critical",
            "message": (
                f"Average utilization {util:.0%} exceeds 100%. "
                "Teams are chronically overloaded — risk of burnout and quality degradation."
            ),
        })
    elif util > 0.90:
        alerts.append({
            "level": "high",
            "message": (
                f"Average utilization {util:.0%} is above sustainable 90% threshold. "
                "Monitor burnout indicators and consider capacity planning."
            ),
        })

    critical_over = [t for t in over if t.get("burnout_risk") == "critical"]
    if critical_over:
        team_names = ", ".join(t["team"] for t in critical_over[:3])
        alerts.append({
            "level": "critical",
            "message": (
                f"Critical burnout risk in {len(critical_over)} team(s): {team_names}. "
                "Utilization >110% — immediate hiring or scope reduction needed."
            ),
        })

    if len(under) > 0 and len(over) > 0:
        alerts.append({
            "level": "medium",
            "message": (
                f"{len(over)} overutilized team(s) while {len(under)} team(s) are under 50% utilized. "
                "Rebalance workload or reorganize team structure."
            ),
        })
    elif len(under) > 0:
        total_under_hc = sum(t["headcount"] for t in under)
        alerts.append({
            "level": "medium",
            "message": (
                f"{total_under_hc} FTEs across {len(under)} team(s) are under 50% utilized. "
                "Opportunity to redirect capacity to higher-value work."
            ),
        })

    if rev_fte > 0 and rev_fte < 5_000_000:  # < $50k/FTE/year
        alerts.append({
            "level": "medium",
            "message": (
                f"Revenue per FTE ${rev_fte / 100:,.0f} is below $50k benchmark. "
                "Review pricing, product mix, or team structure."
            ),
        })

    return alerts


# -- LLM Narrative ------------------------------------------------------------

async def _generate_resource_narrative(metrics: dict[str, Any], settings) -> str:
    """Optional LLM narrative -- falls back to rule-based summary."""
    try:
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import HumanMessage

        llm = ChatOpenAI(
            model=settings.openai_model,
            temperature=0.3,
            max_tokens=300,
            api_key=settings.openai_api_key,
        )
        util  = metrics["avg_utilization_rate"]
        hc    = metrics["total_headcount"]
        over  = len(metrics.get("overutilized_teams", []))
        under = len(metrics.get("underutilized_teams", []))
        prompt = (
            f"Resource analysis: headcount={hc}, avg_utilization={util:.0%}, "
            f"overutilized_teams={over}, underutilized_teams={under}. "
            "Write a 2-sentence COO-level insight on resource efficiency."
        )
        resp = await llm.ainvoke([HumanMessage(content=prompt)])
        return resp.content.strip()
    except Exception:
        util = metrics.get("avg_utilization_rate", 0.0)
        hc   = metrics.get("total_headcount", 0)
        return (
            f"{hc} FTEs at {util:.0%} average utilization. "
            f"{len(metrics.get('overutilized_teams', []))} overutilized team(s) detected."
        )


# -- LangGraph Node -----------------------------------------------------------

async def run_resource_agent(state: COOState, config: dict) -> dict[str, Any]:
    """
    COO Resource Skill.
    done_when: state['resources']['avg_utilization_rate'] is a float.
    """
    csv_text = state.get("resource_csv") or ""

    if not csv_text.strip():
        logger.info("COO ResourceAgent: no resource_csv provided -- skipping")
        return {"resources": None}

    try:
        rows    = _parse_resource_csv(csv_text)
        metrics = _compute_resource_metrics(rows)
        alerts  = _build_resource_alerts(metrics)
        metrics["alerts"] = alerts

        try:
            from app.config import get_settings
            settings = get_settings()
            metrics["narrative"] = await _generate_resource_narrative(metrics, settings)
        except Exception:
            metrics["narrative"] = ""

        logger.info(
            "COO ResourceAgent: job=%s teams=%d util=%.1f%%",
            state.get("job_id"), len(rows),
            metrics["avg_utilization_rate"] * 100,
        )
        return {"resources": metrics}

    except Exception as exc:
        logger.exception("COO ResourceAgent failed for job=%s", state.get("job_id"))
        return {"resources": None, "error": f"ResourceAgent error: {exc}"}
