"""
Key Risk Indicators (KRI) Agent

Monitors KRIs against amber/red thresholds, detects breaches, scores the KRI portfolio,
and surfaces leading indicators of emerging risk before losses occur.
Pure calculation — no LLM required.
"""

from __future__ import annotations

import csv
from collections import Counter
from typing import Any

from app.agents.risk.state import RiskState, RiskStepLog


# ── Parsing ────────────────────────────────────────────────────────────────────

def _parse_kri_csv(csv_text: str) -> list[dict[str, Any]]:
    """Parse KRI CSV with flexible column detection."""
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

    name_col    = _col("kri", "kri_name", "indicator", "name")
    category_col = _col("category", "type", "domain")
    value_col   = _col("current_value", "value", "current", "actual")
    red_col     = _col("threshold_red", "red_threshold", "red_limit", "limit_red")
    amber_col   = _col("threshold_amber", "amber_threshold", "amber_limit", "limit_amber")
    unit_col    = _col("unit", "measure", "units")
    trend_col   = _col("trend", "direction", "movement")
    owner_col   = _col("owner", "kri_owner", "responsible")

    rows: list[dict[str, Any]] = []
    for i, row in enumerate(reader, start=1):
        try:
            def _flt(col: str | None, default: float = 0.0) -> float:
                if not col or not row.get(col):
                    return default
                try:
                    return float(str(row[col]).replace(",", "").replace("%", "").strip())
                except (ValueError, TypeError):
                    return default

            name      = (row.get(name_col) or f"KRI-{i:02d}").strip() if name_col else f"KRI-{i:02d}"
            category  = (row.get(category_col) or "operational").strip().lower() if category_col else "operational"
            value     = _flt(value_col)
            red       = _flt(red_col, default=float("inf"))
            amber     = _flt(amber_col, default=float("inf"))
            unit      = (row.get(unit_col) or "").strip() if unit_col else ""
            trend     = (row.get(trend_col) or "stable").strip().lower() if trend_col else "stable"
            owner     = (row.get(owner_col) or "Unassigned").strip() if owner_col else "Unassigned"

            # Determine breach status
            # Supports both "higher is worse" (default) and lower-is-worse KRIs
            # Convention: if red < amber, lower is worse (e.g. liquidity ratio)
            lower_is_worse = (red < amber) if (red != float("inf") and amber != float("inf")) else False

            if lower_is_worse:
                if value <= red:
                    breach = "red"
                elif value <= amber:
                    breach = "amber"
                else:
                    breach = "green"
            else:
                if red != float("inf") and value >= red:
                    breach = "red"
                elif amber != float("inf") and value >= amber:
                    breach = "amber"
                else:
                    breach = "green"

            rows.append({
                "name":            name,
                "category":        category,
                "value":           value,
                "threshold_red":   red,
                "threshold_amber": amber,
                "unit":            unit,
                "trend":           trend,
                "owner":           owner,
                "breach":          breach,
                "lower_is_worse":  lower_is_worse,
            })
        except Exception:
            pass

    return rows


# ── Computation ────────────────────────────────────────────────────────────────

def _compute_kri_metrics(kris: list[dict[str, Any]]) -> dict[str, Any]:
    """Pure computation — no LLM, no I/O."""
    total = len(kris)
    if total == 0:
        return {
            "total_kris": 0,
            "breached_red": [],
            "breached_amber": [],
            "green_kris": 0,
            "by_breach": {"red": 0, "amber": 0, "green": 0},
            "by_category": {},
            "worsening_kris": [],
            "composite_kri_score": 0.0,
        }

    breached_red   = [k for k in kris if k["breach"] == "red"]
    breached_amber = [k for k in kris if k["breach"] == "amber"]
    green_kris     = [k for k in kris if k["breach"] == "green"]

    by_category = Counter(k["category"] for k in kris)

    # KRIs trending worse
    worsening = [
        k for k in kris
        if k["trend"] in ("up", "increasing", "worsening", "deteriorating")
        and k["breach"] in ("red", "amber")
    ]

    # Composite KRI score 0-10 (higher = worse risk posture)
    # Weighted: red = 3pts, amber = 1pt, then normalised to 10
    weighted_sum = len(breached_red) * 3 + len(breached_amber) * 1
    max_possible = total * 3  # all red
    composite = round((weighted_sum / max_possible) * 10.0, 1) if max_possible > 0 else 0.0

    return {
        "total_kris":          total,
        "breached_red": [
            {"name": k["name"], "value": k["value"],
             "threshold_red": k["threshold_red"], "unit": k["unit"],
             "category": k["category"], "trend": k["trend"]}
            for k in breached_red
        ],
        "breached_amber": [
            {"name": k["name"], "value": k["value"],
             "threshold_amber": k["threshold_amber"], "unit": k["unit"],
             "category": k["category"], "trend": k["trend"]}
            for k in breached_amber
        ],
        "green_kris":          len(green_kris),
        "by_breach":           {
            "red":   len(breached_red),
            "amber": len(breached_amber),
            "green": len(green_kris),
        },
        "by_category":         dict(by_category),
        "worsening_kris": [
            {"name": k["name"], "breach": k["breach"], "trend": k["trend"]}
            for k in worsening
        ],
        "composite_kri_score": composite,
    }


# ── Alerts ─────────────────────────────────────────────────────────────────────

def _build_kri_alerts(metrics: dict[str, Any]) -> list[dict[str, str]]:
    alerts: list[dict[str, str]] = []

    red_count = len(metrics.get("breached_red", []))
    if red_count:
        names = ", ".join(k["name"] for k in metrics["breached_red"][:3])
        alerts.append({
            "level": "critical",
            "message": (
                f"{red_count} KRI(s) breached RED threshold — immediate action required: {names}"
            ),
        })

    amber_count = len(metrics.get("breached_amber", []))
    if amber_count > 2:
        alerts.append({
            "level": "warning",
            "message": f"{amber_count} KRIs in AMBER zone — monitor closely and prepare response plans.",
        })

    worsening_count = len(metrics.get("worsening_kris", []))
    if worsening_count:
        alerts.append({
            "level": "warning",
            "message": (
                f"{worsening_count} KRI(s) are trending adversely — "
                "early intervention may prevent escalation to red."
            ),
        })

    score = metrics.get("composite_kri_score", 0)
    if score >= 6.0:
        alerts.append({
            "level": "critical",
            "message": f"Composite KRI score {score}/10 — risk appetite materially exceeded.",
        })

    return alerts


# ── Narrative ──────────────────────────────────────────────────────────────────

async def _generate_kri_narrative(metrics: dict[str, Any], settings: Any) -> str:
    total     = metrics.get("total_kris", 0)
    red       = len(metrics.get("breached_red", []))
    amber     = len(metrics.get("breached_amber", []))
    score     = metrics.get("composite_kri_score", 0)
    worsening = len(metrics.get("worsening_kris", []))

    lines = [
        f"Monitoring {total} Key Risk Indicators; composite score {score}/10.",
        f"{red} in red zone, {amber} in amber zone.",
    ]
    if worsening:
        lines.append(f"{worsening} KRI(s) trending adversely — early warning signals active.")
    else:
        lines.append("No adverse KRI trends detected in current period.")
    return " ".join(lines)


# ── Node ───────────────────────────────────────────────────────────────────────

async def run_kri_agent(state: RiskState, config: dict) -> dict[str, Any]:
    """KRI Skill Agent — done_when: state['kris']['total_kris'] is int."""
    logs: list[RiskStepLog] = state.get("logs") or []
    result: dict[str, Any] = {"kris": None, "logs": logs, "error": None}

    try:
        rows    = _parse_kri_csv(state.get("kri_csv") or "")
        metrics = _compute_kri_metrics(rows)
        alerts  = _build_kri_alerts(metrics)
        narr    = await _generate_kri_narrative(metrics, config.get("settings"))

        result["kris"] = {**metrics, "alerts": alerts, "narrative": narr}
        logs.append(RiskStepLog(
            node="kri_agent", status="completed",
            message=f"Evaluated {len(rows)} KRIs",
            metrics={"composite_kri_score": metrics["composite_kri_score"]},
        ))
    except Exception as exc:
        result["error"] = f"kri_agent failed: {exc}"
        logs.append(RiskStepLog(node="kri_agent", status="failed", message=str(exc)))

    return result
