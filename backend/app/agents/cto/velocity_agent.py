"""
Velocity Agent — CTO Skill 4 of 5.

Responsibility: Analyze sprint velocity data to assess engineering throughput.

Computes:
- Average velocity (story points or tickets completed per sprint)
- Velocity trend: up / flat / down
- Sprint predictability score (actual / planned ratio consistency)
- Bottleneck detection: sprints with low completion rate
- Carry-over ratio (work carried to next sprint)

Input: sprint_csv — Jira / Linear / GitHub Projects CSV export with columns:
  sprint_name, [sprint_number], planned_points, completed_points, [start_date], [end_date]
  or: sprint, planned, completed, [date]

done_when: state['velocity']['avg_velocity'] is a float.
"""
from __future__ import annotations

import csv
import io
import logging
import statistics
from collections import defaultdict
from typing import Any

from app.agents.cto.state import CTOState, CTORunConfig, CTOSkillResult

logger = logging.getLogger(__name__)

LOW_COMPLETION_THRESHOLD = 0.70   # < 70% completion rate = bottleneck sprint
PREDICTABILITY_TARGET    = 0.85   # target: 85%+ sprints within 20% of avg


def _parse_sprint_csv(csv_text: str) -> list[dict[str, Any]]:
    """Parse sprint CSV — flexible column detection."""
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

    name_col      = _col("sprint_name", "sprint", "name", "iteration")
    planned_col   = _col("planned_points", "planned", "story_points_planned", "capacity", "commitment")
    completed_col = _col("completed_points", "completed", "story_points_completed", "velocity", "done")
    date_col      = _col("start_date", "date", "sprint_start", "period")
    carryover_col = _col("carry_over", "carryover", "carried_over", "rolled_over")

    if not planned_col or not completed_col:
        logger.warning("VelocityAgent: could not detect planned/completed columns")
        return rows

    for i, row in enumerate(reader):
        name = row.get(name_col, f"Sprint {i+1}") if name_col else f"Sprint {i+1}"
        raw_planned   = (row.get(planned_col, "0") or "0").strip()
        raw_completed = (row.get(completed_col, "0") or "0").strip()
        date = row.get(date_col, "") if date_col else ""
        raw_carryover = (row.get(carryover_col, "0") or "0").strip() if carryover_col else "0"

        try:
            planned = float(raw_planned)
            completed = float(raw_completed)
        except (ValueError, TypeError):
            continue

        if planned <= 0:
            continue

        try:
            carryover = float(raw_carryover)
        except (ValueError, TypeError):
            carryover = 0.0

        completion_rate = round(completed / planned, 3) if planned > 0 else 0

        rows.append({
            "sprint": str(name).strip(),
            "planned": planned,
            "completed": completed,
            "carryover": carryover,
            "completion_rate": completion_rate,
            "date": str(date)[:10],
        })

    return rows


def _compute_velocity_metrics(sprints: list[dict[str, Any]]) -> dict[str, Any]:
    """Pure calculation."""
    if not sprints:
        return {}

    n = len(sprints)
    velocities = [s["completed"] for s in sprints]
    completion_rates = [s["completion_rate"] for s in sprints]

    avg_velocity = round(statistics.mean(velocities), 1)
    velocity_std = round(statistics.stdev(velocities), 1) if n >= 2 else 0.0

    # Trend: compare first third vs last third
    trend = "flat"
    if n >= 6:
        third = n // 3
        early_avg = statistics.mean(velocities[:third])
        recent_avg = statistics.mean(velocities[-third:])
        if early_avg > 0:
            change = (recent_avg - early_avg) / early_avg
            if change > 0.10:
                trend = "up"
            elif change < -0.10:
                trend = "down"

    # Predictability: % of sprints where completion rate is within ±20% of target (1.0)
    predictable_sprints = sum(1 for r in completion_rates if 0.80 <= r <= 1.20)
    predictability_score = round(predictable_sprints / n, 3) if n > 0 else 0.0

    # Bottleneck sprints: low completion rate
    bottleneck_sprints = [
        {"sprint": s["sprint"], "completion_rate": s["completion_rate"], "completed": s["completed"]}
        for s in sprints
        if s["completion_rate"] < LOW_COMPLETION_THRESHOLD
    ]

    # Carryover ratio
    total_planned = sum(s["planned"] for s in sprints)
    total_carryover = sum(s["carryover"] for s in sprints)
    carryover_ratio = round(total_carryover / total_planned, 3) if total_planned > 0 else 0.0

    # Sprint series for charts
    sprint_series = [
        {
            "sprint": s["sprint"],
            "planned": s["planned"],
            "completed": s["completed"],
            "completion_rate_pct": round(s["completion_rate"] * 100, 1),
            "date": s["date"],
        }
        for s in sprints
    ]

    # Identify bottleneck areas (sprints with lowest velocity)
    bottlenecks = []
    if bottleneck_sprints:
        bottlenecks.append({
            "area": f"{len(bottleneck_sprints)} sprints below 70% completion",
            "impact": f"Average completion: {statistics.mean(s['completion_rate'] for s in bottleneck_sprints)*100:.0f}%",
        })
    if carryover_ratio > 0.15:
        bottlenecks.append({
            "area": "High carryover rate",
            "impact": f"{carryover_ratio*100:.0f}% of planned work carried to next sprint",
        })
    if velocity_std / avg_velocity > 0.30 if avg_velocity > 0 else False:
        bottlenecks.append({
            "area": "High velocity variance",
            "impact": f"Velocity ranges ±{velocity_std:.0f} pts — unpredictable throughput",
        })

    return {
        "sprints_analyzed": n,
        "avg_velocity": avg_velocity,
        "velocity_std": velocity_std,
        "velocity_trend": trend,
        "predictability_score": predictability_score,
        "carryover_ratio": carryover_ratio,
        "bottleneck_sprints": bottleneck_sprints[:5],
        "bottlenecks": bottlenecks,
        "sprint_series": sprint_series,
        "total_planned": total_planned,
        "total_completed": sum(s["completed"] for s in sprints),
    }


def _build_velocity_alerts(metrics: dict[str, Any]) -> list[dict[str, str]]:
    alerts = []

    predictability = metrics.get("predictability_score", 1.0)
    if predictability < 0.60:
        alerts.append({
            "level": "warning",
            "message": (
                f"Sprint predictability is {predictability*100:.0f}% — "
                f"team is consistently missing planned scope. Review estimation process."
            ),
        })

    trend = metrics.get("velocity_trend")
    if trend == "down":
        alerts.append({
            "level": "warning",
            "message": "Engineering velocity is declining. Check for blockers, burnout, or scope creep.",
        })

    carryover = metrics.get("carryover_ratio", 0)
    if carryover > 0.25:
        alerts.append({
            "level": "warning",
            "message": (
                f"{carryover*100:.0f}% carryover rate — "
                "team is over-committing each sprint. Reduce sprint scope by 20-25%."
            ),
        })

    return alerts


async def _generate_velocity_narrative(
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

    alert_text = (
        "\n".join(f"- [{a['level'].upper()}] {a['message']}" for a in alerts)
        or "No critical alerts."
    )

    messages = [
        SystemMessage(content=(
            "Sen deneyimli bir CTO ve mühendislik liderisisin. "
            "Sprint velocity verilerini analiz et ve Türkçe olarak kısa, eyleme dönüştürülebilir bir özet yaz. "
            "Yanıt şu yapıda olsun:\n"
            "1. Ekip verimliliğinin 1-2 cümlelik değerlendirmesi (velocity trend ve öngörülebilirlik odaklı)\n"
            "2. En kritik sorun (carryover, düşen velocity veya öngörülemezlik)\n"
            "3. Sonraki sprint'te uygulanabilecek 2-3 somut iyileştirme (scrum/kanban pratikleri)\n"
            "Teknik olmayan yöneticinin anlayacağı sade dilde yaz."
        )),
        HumanMessage(content=(
            f"Analiz Edilen Sprint: {metrics['sprints_analyzed']}\n"
            f"Ortalama Velocity: {metrics['avg_velocity']} puan/sprint\n"
            f"Velocity Trendi: {metrics['velocity_trend']}\n"
            f"Öngörülebilirlik Skoru: %{metrics['predictability_score']*100:.0f}\n"
            f"Devredilen İş Oranı: %{metrics['carryover_ratio']*100:.0f}\n\n"
            f"Uyarılar:\n{alert_text}"
        )),
    ]
    response = await llm.ainvoke(messages)
    return response.content.strip()


async def run_velocity_agent(
    state: CTOState,
    config: CTORunConfig,
) -> CTOSkillResult:
    """
    VelocityAgent Skill.
    done_when: state['velocity']['avg_velocity'] is a float.
    """
    sprint_csv = state.get("sprint_csv")
    if not sprint_csv:
        return CTOSkillResult(
            ok=True,
            patch={"velocity": None},
            confidence=1.0,
            detail="No sprint data provided — VelocityAgent skipped.",
        )

    try:
        from app.config import get_settings
        settings = get_settings()

        sprints = _parse_sprint_csv(sprint_csv)
        if not sprints:
            return CTOSkillResult(
                ok=False,
                detail="Could not parse sprint CSV — no valid rows found.",
                confidence=0.3,
                needs_review=True,
            )

        metrics = _compute_velocity_metrics(sprints)
        alerts = _build_velocity_alerts(metrics)
        narrative = await _generate_velocity_narrative(metrics, alerts, settings)

        metrics["alerts"] = alerts
        metrics["narrative"] = narrative

        has_critical = any(a["level"] == "critical" for a in alerts)
        confidence = 0.90 if not has_critical else 0.82

        logger.info(
            "VelocityAgent: job=%s sprints=%d avg_vel=%.1f trend=%s predictability=%.2f",
            state.get("job_id"),
            metrics["sprints_analyzed"],
            metrics["avg_velocity"],
            metrics["velocity_trend"],
            metrics["predictability_score"],
        )

        return CTOSkillResult(
            ok=True,
            patch={"velocity": metrics},
            confidence=confidence,
            needs_review=has_critical,
            detail=(
                f"Velocity: {metrics['avg_velocity']} pts/sprint, "
                f"trend: {metrics['velocity_trend']}, "
                f"predictability: {metrics['predictability_score']*100:.0f}%"
            ),
        )

    except Exception as exc:
        logger.exception("VelocityAgent failed for job=%s", state.get("job_id"))
        return CTOSkillResult(ok=False, detail=f"VelocityAgent error: {exc}")
