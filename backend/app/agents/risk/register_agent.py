"""
Risk Register Agent

Parses the enterprise risk register, scores each risk by likelihood × impact,
builds a heatmap, detects unmitigated critical risks, and recommends actions.
Pure calculation — no LLM required.
"""

from __future__ import annotations

import csv
from collections import Counter
from typing import Any

from app.agents.risk.state import RiskState, RiskStepLog

# ── Constants ──────────────────────────────────────────────────────────────────

# 5 × 5 risk heatmap  (likelihood 1-5) × (impact 1-5) → colour band
def _heat_band(score: float) -> str:
    """Map raw score (1-25) to a colour band used in enterprise heatmaps."""
    if score >= 15:
        return "critical"   # red zone
    if score >= 8:
        return "high"       # orange zone
    if score >= 4:
        return "medium"     # yellow zone
    return "low"            # green zone


_VALID_STATUSES = {"open", "mitigated", "accepted", "transferred", "closed"}
_VALID_CATEGORIES = {
    "operational", "financial", "strategic", "compliance", "technology",
    "reputational", "legal", "people", "environmental", "cyber", "other",
}


# ── Parsing ────────────────────────────────────────────────────────────────────

def _parse_register_csv(csv_text: str) -> list[dict[str, Any]]:
    """Parse risk register CSV with flexible column detection."""
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

    id_col          = _col("risk_id", "id", "ref")
    title_col       = _col("risk", "title", "description", "risk_title")
    category_col    = _col("category", "type", "domain")
    likelihood_col  = _col("likelihood", "probability", "prob")
    impact_col      = _col("impact", "severity", "consequence")
    owner_col       = _col("owner", "risk_owner", "responsible")
    status_col      = _col("status", "state", "risk_status")
    mitigation_col  = _col("mitigation", "control", "treatment", "action")

    rows: list[dict[str, Any]] = []
    for i, row in enumerate(reader, start=1):
        try:
            def _safe_int(col, default: int = 3) -> int:
                if not col or not row.get(col):
                    return default
                try:
                    return max(1, min(5, int(float(str(row[col]).strip()))))
                except (ValueError, TypeError):
                    return default

            risk_id    = (row.get(id_col) or f"R{i:03d}").strip() if id_col else f"R{i:03d}"
            title      = (row.get(title_col) or f"Risk {i}").strip() if title_col else f"Risk {i}"
            category   = (row.get(category_col) or "operational").strip().lower() if category_col else "operational"
            likelihood = _safe_int(likelihood_col)
            impact     = _safe_int(impact_col)
            owner      = (row.get(owner_col) or "Unassigned").strip() if owner_col else "Unassigned"
            status     = (row.get(status_col) or "open").strip().lower() if status_col else "open"
            mitigation = (row.get(mitigation_col) or "").strip() if mitigation_col else ""

            if category not in _VALID_CATEGORIES:
                category = "other"
            if status not in _VALID_STATUSES:
                status = "open"

            raw_score     = likelihood * impact
            residual_lkh  = max(1, likelihood - (1 if mitigation else 0))
            residual_imp  = impact  # impact rarely changes post-mitigation in simple models
            residual_score = residual_lkh * residual_imp

            rows.append({
                "risk_id":        risk_id,
                "title":          title,
                "category":       category,
                "likelihood":     likelihood,
                "impact":         impact,
                "raw_score":      raw_score,
                "heat_band":      _heat_band(raw_score),
                "residual_score": residual_score,
                "residual_band":  _heat_band(residual_score),
                "owner":          owner,
                "status":         status,
                "mitigation":     mitigation,
                "has_mitigation": bool(mitigation),
            })
        except Exception:
            pass

    return rows


# ── Computation ────────────────────────────────────────────────────────────────

def _compute_register_metrics(risks: list[dict[str, Any]]) -> dict[str, Any]:
    """Pure computation — no LLM, no I/O."""
    total = len(risks)
    if total == 0:
        return {
            "total_risks": 0,
            "by_band": {}, "by_category": {}, "by_status": {}, "by_owner": {},
            "unmitigated_critical": [],
            "top_risks": [],
            "avg_raw_score": 0.0,
            "avg_residual_score": 0.0,
            "mitigation_coverage": 0.0,
            "enterprise_risk_score": 0.0,
        }

    by_band     = Counter(r["heat_band"] for r in risks)
    by_category = Counter(r["category"] for r in risks)
    by_status   = Counter(r["status"] for r in risks)
    by_owner    = Counter(r["owner"] for r in risks)

    open_risks = [r for r in risks if r["status"] == "open"]
    unmitigated_critical = [
        r for r in open_risks
        if r["heat_band"] in ("critical", "high") and not r["has_mitigation"]
    ]

    # Top 5 risks by raw score
    top_risks = sorted(risks, key=lambda r: r["raw_score"], reverse=True)[:5]

    avg_raw      = sum(r["raw_score"] for r in risks) / total
    avg_residual = sum(r["residual_score"] for r in risks) / total

    mitigated = [r for r in risks if r["has_mitigation"]]
    mitigation_coverage = len(mitigated) / total if total > 0 else 0.0

    # Enterprise risk score 0-10 (higher = worse)
    # Normalise avg residual score (max possible = 25) to 0-10
    enterprise_risk_score = round(min(10.0, (avg_residual / 25.0) * 10.0), 1)

    return {
        "total_risks":             total,
        "by_band":                 dict(by_band),
        "by_category":             dict(by_category),
        "by_status":               dict(by_status),
        "by_owner":                dict(by_owner),
        "unmitigated_critical":    [
            {"risk_id": r["risk_id"], "title": r["title"],
             "band": r["heat_band"], "score": r["raw_score"]}
            for r in unmitigated_critical
        ],
        "top_risks":               [
            {"risk_id": r["risk_id"], "title": r["title"],
             "category": r["category"], "score": r["raw_score"],
             "band": r["heat_band"], "owner": r["owner"],
             "mitigation": r["mitigation"] or None}
            for r in top_risks
        ],
        "avg_raw_score":           round(avg_raw, 2),
        "avg_residual_score":      round(avg_residual, 2),
        "mitigation_coverage":     round(mitigation_coverage, 3),
        "enterprise_risk_score":   enterprise_risk_score,
    }


# ── Alerts ─────────────────────────────────────────────────────────────────────

def _build_register_alerts(metrics: dict[str, Any]) -> list[dict[str, str]]:
    alerts: list[dict[str, str]] = []

    unmitigated = metrics.get("unmitigated_critical", [])
    if unmitigated:
        alerts.append({
            "level": "critical",
            "message": (
                f"{len(unmitigated)} critical/high risk(s) have NO mitigation — "
                f"immediate treatment required: {', '.join(r['title'][:30] for r in unmitigated[:3])}"
            ),
        })

    coverage = metrics.get("mitigation_coverage", 1.0)
    if coverage < 0.50:
        alerts.append({
            "level": "warning",
            "message": (
                f"Only {coverage:.0%} of risks have mitigation controls — "
                "significant exposure remains untreated."
            ),
        })

    if metrics.get("by_band", {}).get("critical", 0) > 3:
        alerts.append({
            "level": "warning",
            "message": (
                f"{metrics['by_band']['critical']} risks in CRITICAL zone — "
                "board-level attention recommended."
            ),
        })

    score = metrics.get("enterprise_risk_score", 0)
    if score >= 7.0:
        alerts.append({
            "level": "critical",
            "message": f"Enterprise risk score {score}/10 — risk appetite likely breached.",
        })

    return alerts


# ── Narrative ──────────────────────────────────────────────────────────────────

async def _generate_register_narrative(metrics: dict[str, Any], settings: Any) -> str:
    total    = metrics.get("total_risks", 0)
    score    = metrics.get("enterprise_risk_score", 0)
    crit     = metrics.get("by_band", {}).get("critical", 0)
    no_mit   = len(metrics.get("unmitigated_critical", []))
    coverage = metrics.get("mitigation_coverage", 0)

    lines = [
        f"Risk register contains {total} risks with enterprise risk score {score}/10.",
        f"{crit} risks in the critical zone; mitigation coverage {coverage:.0%}.",
    ]
    if no_mit:
        lines.append(f"{no_mit} critical/high risk(s) lack any mitigation — prioritise treatment immediately.")
    else:
        lines.append("All critical risks have at least partial mitigation in place.")
    return " ".join(lines)


# ── Node ───────────────────────────────────────────────────────────────────────

async def run_register_agent(state: RiskState, config: dict) -> dict[str, Any]:
    """Risk Register Skill Agent — done_when: state['register']['total_risks'] is int."""
    logs: list[RiskStepLog] = state.get("logs") or []
    result: dict[str, Any] = {"register": None, "logs": logs, "error": None}

    try:
        rows    = _parse_register_csv(state.get("register_csv") or "")
        metrics = _compute_register_metrics(rows)
        alerts  = _build_register_alerts(metrics)
        narr    = await _generate_register_narrative(metrics, config.get("settings"))

        result["register"] = {**metrics, "alerts": alerts, "narrative": narr}
        logs.append(RiskStepLog(
            node="register_agent", status="completed",
            message=f"Scored {len(rows)} risks",
            metrics={"enterprise_risk_score": metrics["enterprise_risk_score"]},
        ))
    except Exception as exc:
        result["error"] = f"register_agent failed: {exc}"
        logs.append(RiskStepLog(node="register_agent", status="failed", message=str(exc)))

    return result
