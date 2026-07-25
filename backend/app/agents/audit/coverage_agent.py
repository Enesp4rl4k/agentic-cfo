"""
Audit Coverage Agent

Tracks audit universe coverage: which auditable units have been reviewed,
identifies gaps in high-risk areas, and flags overdue scheduled audits.
Pure calculation — no LLM required.
"""

from __future__ import annotations

import csv
from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from app.agents.audit.state import AuditState, AuditStepLog


_RISK_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
_FREQ_MONTHS = {
    "annual": 12, "semi-annual": 6, "quarterly": 3,
    "biennial": 24, "triennial": 36, "continuous": 1,
}


def _parse_coverage_csv(csv_text: str) -> list[dict[str, Any]]:
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

    unit_col    = _col("unit", "name", "auditable_unit", "entity")
    cat_col     = _col("category", "type", "domain")
    last_col    = _col("last_audit", "last_audited", "last_review")
    freq_col    = _col("frequency", "audit_frequency", "cycle")
    risk_col    = _col("risk_rating", "risk", "risk_level")
    next_col    = _col("scheduled_next", "next_audit", "next_scheduled")

    rows: list[dict[str, Any]] = []
    today = datetime.now()

    for i, row in enumerate(reader, start=1):
        try:
            def _parse_date(raw: str | None) -> datetime | None:
                if not raw:
                    return None
                for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
                    try:
                        return datetime.strptime(str(raw).strip(), fmt)
                    except ValueError:
                        pass
                return None

            unit     = (row.get(unit_col) or f"Unit {i}").strip() if unit_col else f"Unit {i}"
            cat      = (row.get(cat_col) or "general").strip().lower() if cat_col else "general"
            risk     = (row.get(risk_col) or "medium").strip().lower() if risk_col else "medium"
            freq_str = (row.get(freq_col) or "annual").strip().lower() if freq_col else "annual"
            last_dt  = _parse_date(row.get(last_col)) if last_col else None
            next_dt  = _parse_date(row.get(next_col)) if next_col else None

            if risk not in _RISK_ORDER:
                risk = "medium"

            freq_months = _FREQ_MONTHS.get(freq_str, 12)

            # Calculate overdue status
            overdue = False
            months_overdue = 0
            audited = last_dt is not None

            if audited:
                expected_next = last_dt + timedelta(days=freq_months * 30.5)
                if today > expected_next:
                    overdue = True
                    months_overdue = int((today - expected_next).days / 30.5)
            else:
                # Never audited — mark as overdue if risk is high/critical
                overdue = risk in ("high", "critical")
                months_overdue = 999  # sentinel: never audited

            rows.append({
                "unit": unit, "category": cat, "risk": risk,
                "frequency": freq_str, "freq_months": freq_months,
                "last_audit": last_dt, "next_scheduled": next_dt,
                "audited": audited, "overdue": overdue,
                "months_overdue": months_overdue,
            })
        except Exception:
            pass
    return rows


def _compute_coverage_metrics(units: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(units)
    if total == 0:
        return {
            "total_units": 0,
            "audited_units": 0, "coverage_rate": 0.0,
            "overdue_units": [], "by_risk": {}, "by_category": {},
            "high_risk_coverage": 0.0, "audit_backlog": 0,
        }

    audited   = [u for u in units if u["audited"]]
    overdue   = [u for u in units if u["overdue"]]
    by_risk   = Counter(u["risk"] for u in units)
    by_cat    = Counter(u["category"] for u in units)

    coverage_rate = len(audited) / total

    # High/critical risk coverage
    high_risk_units = [u for u in units if u["risk"] in ("high", "critical")]
    hr_audited      = [u for u in high_risk_units if u["audited"]]
    high_risk_coverage = len(hr_audited) / len(high_risk_units) if high_risk_units else 1.0

    # Sort overdue by risk priority then months_overdue
    sorted_overdue = sorted(
        overdue,
        key=lambda u: (_RISK_ORDER.get(u["risk"], 4), -u["months_overdue"]),
    )

    return {
        "total_units":         total,
        "audited_units":       len(audited),
        "coverage_rate":       round(coverage_rate, 3),
        "overdue_units": [
            {"unit": u["unit"], "risk": u["risk"], "months_overdue": u["months_overdue"],
             "category": u["category"]}
            for u in sorted_overdue[:8]
        ],
        "by_risk":             dict(by_risk),
        "by_category":         dict(by_cat),
        "high_risk_coverage":  round(high_risk_coverage, 3),
        "audit_backlog":       len(overdue),
    }


def _build_coverage_alerts(metrics: dict[str, Any]) -> list[dict[str, str]]:
    alerts: list[dict[str, str]] = []

    if metrics.get("high_risk_coverage", 1.0) < 0.80:
        alerts.append({
            "level": "critical",
            "message": (
                f"High-risk audit coverage only {metrics['high_risk_coverage']:.0%} — "
                "material audit gaps in critical business areas."
            ),
        })

    if metrics.get("coverage_rate", 1.0) < 0.60:
        alerts.append({
            "level": "warning",
            "message": f"Overall audit universe coverage {metrics['coverage_rate']:.0%} — significant gaps.",
        })

    backlog = metrics.get("audit_backlog", 0)
    if backlog > 5:
        alerts.append({
            "level": "warning",
            "message": f"Audit backlog: {backlog} units overdue for review — resourcing issue likely.",
        })

    return alerts


async def run_coverage_agent(state: AuditState, config: dict) -> dict[str, Any]:
    logs: list[AuditStepLog] = list(state.get("logs") or [])
    result: dict[str, Any] = {"coverage": None, "logs": logs, "error": None}
    try:
        rows    = _parse_coverage_csv(state.get("coverage_csv") or "")
        metrics = _compute_coverage_metrics(rows)
        alerts  = _build_coverage_alerts(metrics)
        result["coverage"] = {
            **metrics, "alerts": alerts,
            "narrative": (
                f"Audit universe: {metrics['total_units']} units, "
                f"{metrics['coverage_rate']:.0%} covered, "
                f"high-risk coverage {metrics['high_risk_coverage']:.0%}."
            ),
        }
        logs.append(AuditStepLog(
            node="coverage_agent", status="completed",
            message=f"Assessed {len(rows)} auditable units",
            metrics={"coverage_rate": metrics["coverage_rate"]},
        ))
    except Exception as exc:
        result["error"] = f"coverage_agent failed: {exc}"
        logs.append(AuditStepLog(node="coverage_agent", status="failed", message=str(exc)))
    return result
