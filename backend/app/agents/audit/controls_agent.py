"""
Audit Controls Agent

Scores design and operating effectiveness of internal controls,
detects weaknesses, and tracks last-tested dates.
Pure calculation — no LLM required.
"""

from __future__ import annotations

import csv
from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from app.agents.audit.state import AuditState, AuditStepLog


# ── Parsing ────────────────────────────────────────────────────────────────────

def _parse_controls_csv(csv_text: str) -> list[dict[str, Any]]:
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

    id_col      = _col("control_id", "id", "ref")
    name_col    = _col("name", "control", "control_name")
    cat_col     = _col("category", "type", "domain")
    design_col  = _col("design_effectiveness", "design", "design_score")
    operate_col = _col("operating_effectiveness", "operating", "operating_score")
    tested_col  = _col("last_tested", "last_test_date", "tested_date")
    owner_col   = _col("owner", "control_owner")

    rows: list[dict[str, Any]] = []
    today = datetime.now()

    for i, row in enumerate(reader, start=1):
        try:
            def _score(col: str | None, default: str = "effective") -> str:
                if not col or not row.get(col):
                    return default
                val = str(row[col]).strip().lower()
                if val in ("effective", "adequate", "satisfactory", "pass", "yes", "1"):
                    return "effective"
                if val in ("partially effective", "partial", "needs improvement", "warning"):
                    return "partially_effective"
                if val in ("ineffective", "inadequate", "fail", "no", "0"):
                    return "ineffective"
                return default

            def _parse_date(raw: str | None) -> datetime | None:
                if not raw:
                    return None
                for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
                    try:
                        return datetime.strptime(str(raw).strip(), fmt)
                    except ValueError:
                        pass
                return None

            cid     = (row.get(id_col) or f"C{i:03d}").strip() if id_col else f"C{i:03d}"
            name    = (row.get(name_col) or f"Control {i}").strip() if name_col else f"Control {i}"
            cat     = (row.get(cat_col) or "general").strip().lower() if cat_col else "general"
            design  = _score(design_col)
            operate = _score(operate_col)
            owner   = (row.get(owner_col) or "Unassigned").strip() if owner_col else "Unassigned"
            tested  = _parse_date(row.get(tested_col)) if tested_col else None

            # Overdue for testing: >12 months
            stale = False
            days_since_test = None
            if tested:
                days_since_test = (today - tested).days
                stale = days_since_test > 365

            rows.append({
                "id": cid, "name": name, "category": cat,
                "design": design, "operating": operate,
                "owner": owner, "last_tested": tested,
                "stale": stale, "days_since_test": days_since_test,
            })
        except Exception:
            pass
    return rows


# ── Computation ────────────────────────────────────────────────────────────────

def _compute_controls_metrics(controls: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(controls)
    if total == 0:
        return {
            "total_controls": 0,
            "design_scores": {}, "operating_scores": {},
            "ineffective_controls": [], "stale_controls": 0,
            "control_coverage": 0.0, "overall_control_score": 0.0,
        }

    design_counts   = Counter(c["design"] for c in controls)
    operating_counts = Counter(c["operating"] for c in controls)

    ineffective = [
        c for c in controls
        if c["design"] == "ineffective" or c["operating"] == "ineffective"
    ]
    stale = [c for c in controls if c["stale"]]

    # Overall control score 0-100
    # Effective = 1.0, partially_effective = 0.5, ineffective = 0.0
    def _score(effectiveness: str) -> float:
        return {"effective": 1.0, "partially_effective": 0.5, "ineffective": 0.0}.get(effectiveness, 0.5)

    design_score    = sum(_score(c["design"]) for c in controls) / total * 100
    operating_score = sum(_score(c["operating"]) for c in controls) / total * 100
    overall = round((design_score * 0.40 + operating_score * 0.60), 1)

    tested_count = sum(1 for c in controls if c["last_tested"] is not None)
    control_coverage = tested_count / total if total > 0 else 0.0

    return {
        "total_controls":    total,
        "design_scores":     dict(design_counts),
        "operating_scores":  dict(operating_counts),
        "ineffective_controls": [
            {"id": c["id"], "name": c["name"], "design": c["design"],
             "operating": c["operating"], "owner": c["owner"]}
            for c in ineffective[:5]
        ],
        "stale_controls":      len(stale),
        "control_coverage":    round(control_coverage, 3),
        "overall_control_score": overall,
        "design_score":        round(design_score, 1),
        "operating_score":     round(operating_score, 1),
    }


def _build_controls_alerts(metrics: dict[str, Any]) -> list[dict[str, str]]:
    alerts: list[dict[str, str]] = []

    ineffective = len(metrics.get("ineffective_controls", []))
    if ineffective:
        alerts.append({
            "level": "critical",
            "message": (
                f"{ineffective} ineffective control(s) detected — "
                "material weakness risk; remediate immediately."
            ),
        })

    score = metrics.get("overall_control_score", 100)
    if score < 60:
        alerts.append({
            "level": "warning",
            "message": f"Overall control score {score}/100 — significant control environment weaknesses.",
        })

    stale = metrics.get("stale_controls", 0)
    if stale > metrics.get("total_controls", 1) * 0.30:
        alerts.append({
            "level": "warning",
            "message": f"{stale} controls not tested in >12 months — testing backlog requires attention.",
        })

    return alerts


async def run_controls_agent(state: AuditState, config: dict) -> dict[str, Any]:
    logs: list[AuditStepLog] = list(state.get("logs") or [])
    result: dict[str, Any] = {"controls": None, "logs": logs, "error": None}
    try:
        rows    = _parse_controls_csv(state.get("controls_csv") or "")
        metrics = _compute_controls_metrics(rows)
        alerts  = _build_controls_alerts(metrics)
        result["controls"] = {
            **metrics, "alerts": alerts,
            "narrative": (
                f"{metrics['total_controls']} controls evaluated; "
                f"overall score {metrics['overall_control_score']}/100; "
                f"{len(metrics['ineffective_controls'])} ineffective."
            ),
        }
        logs.append(AuditStepLog(
            node="controls_agent", status="completed",
            message=f"Evaluated {len(rows)} controls",
            metrics={"overall_control_score": metrics["overall_control_score"]},
        ))
    except Exception as exc:
        result["error"] = f"controls_agent failed: {exc}"
        logs.append(AuditStepLog(node="controls_agent", status="failed", message=str(exc)))
    return result
