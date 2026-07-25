"""
Risk Loss Events Agent

Tracks operational loss events: frequency analysis, loss distribution by category,
recovery rates, and trend detection (improving / worsening).
Pure calculation — no LLM required.
"""

from __future__ import annotations

import csv
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

from app.agents.risk.state import RiskState, RiskStepLog


# ── Helpers ────────────────────────────────────────────────────────────────────

def _parse_date(raw: str) -> datetime | None:
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw.strip(), fmt)
        except (ValueError, AttributeError):
            pass
    return None


def _safe_cents(raw: str | None) -> int:
    """Parse a dollar/amount value into integer cents."""
    if not raw:
        return 0
    try:
        val = float(str(raw).replace(",", "").replace("$", "").strip())
        return max(0, int(val * 100))
    except (ValueError, TypeError):
        return 0


# ── Parsing ────────────────────────────────────────────────────────────────────

def _parse_loss_csv(csv_text: str) -> list[dict[str, Any]]:
    """Parse loss events CSV with flexible column detection."""
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

    date_col       = _col("date", "event_date", "loss_date", "occurred")
    category_col   = _col("category", "type", "risk_category")
    description_col = _col("description", "event", "incident", "details")
    gross_col      = _col("gross_loss", "loss", "amount", "gross_amount")
    recovery_col   = _col("recovery", "recovered", "recovery_amount")
    root_col       = _col("root_cause", "cause", "root_cause_category")
    status_col     = _col("status", "resolution_status")

    rows: list[dict[str, Any]] = []
    for i, row in enumerate(reader, start=1):
        try:
            event_date = _parse_date(row.get(date_col) or "") if date_col else None
            category   = (row.get(category_col) or "operational").strip().lower() if category_col else "operational"
            description = (row.get(description_col) or f"Loss event {i}").strip() if description_col else f"Loss event {i}"
            gross_loss = _safe_cents(row.get(gross_col)) if gross_col else 0
            recovery   = _safe_cents(row.get(recovery_col)) if recovery_col else 0
            net_loss   = max(0, gross_loss - recovery)
            root_cause = (row.get(root_col) or "unknown").strip().lower() if root_col else "unknown"
            status     = (row.get(status_col) or "closed").strip().lower() if status_col else "closed"

            rows.append({
                "date":        event_date,
                "category":    category,
                "description": description,
                "gross_loss":  gross_loss,
                "recovery":    recovery,
                "net_loss":    net_loss,
                "root_cause":  root_cause,
                "status":      status,
            })
        except Exception:
            pass

    return rows


# ── Computation ────────────────────────────────────────────────────────────────

def _compute_loss_metrics(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Pure computation — no LLM, no I/O."""
    total = len(events)
    if total == 0:
        return {
            "total_events": 0,
            "total_gross_loss": 0,
            "total_net_loss": 0,
            "total_recovery": 0,
            "recovery_rate": 0.0,
            "avg_net_loss_per_event": 0,
            "by_category": {},
            "by_root_cause": {},
            "top_loss_events": [],
            "open_events": 0,
            "largest_single_loss": 0,
            "loss_trend": "stable",
        }

    total_gross = sum(e["gross_loss"] for e in events)
    total_rec   = sum(e["recovery"] for e in events)
    total_net   = sum(e["net_loss"] for e in events)
    recovery_rate = total_rec / total_gross if total_gross > 0 else 0.0

    # By category (total net loss)
    cat_loss: dict[str, int] = defaultdict(int)
    for e in events:
        cat_loss[e["category"]] += e["net_loss"]

    # By root cause
    rc_counts = Counter(e["root_cause"] for e in events)

    # Top 5 loss events by net loss
    top_events = sorted(events, key=lambda e: e["net_loss"], reverse=True)[:5]

    # Open events
    open_events = [e for e in events if e["status"] in ("open", "in_progress", "pending")]

    # Largest single loss
    largest = max((e["net_loss"] for e in events), default=0)

    # Trend: compare first half vs second half by event count and volume
    sorted_events = sorted([e for e in events if e["date"]], key=lambda e: e["date"])
    trend = "stable"
    if len(sorted_events) >= 4:
        mid = len(sorted_events) // 2
        first_half_loss = sum(e["net_loss"] for e in sorted_events[:mid])
        second_half_loss = sum(e["net_loss"] for e in sorted_events[mid:])
        if first_half_loss > 0:
            change = (second_half_loss - first_half_loss) / first_half_loss
            if change > 0.20:
                trend = "worsening"
            elif change < -0.20:
                trend = "improving"

    return {
        "total_events":            total,
        "total_gross_loss":        total_gross,
        "total_net_loss":          total_net,
        "total_recovery":          total_rec,
        "recovery_rate":           round(recovery_rate, 3),
        "avg_net_loss_per_event":  int(total_net / total) if total > 0 else 0,
        "by_category":             {k: v for k, v in sorted(cat_loss.items(), key=lambda x: -x[1])},
        "by_root_cause":           dict(rc_counts.most_common(5)),
        "top_loss_events": [
            {
                "description": e["description"],
                "gross_loss":  e["gross_loss"],
                "net_loss":    e["net_loss"],
                "category":    e["category"],
                "root_cause":  e["root_cause"],
            }
            for e in top_events
        ],
        "open_events":             len(open_events),
        "largest_single_loss":     largest,
        "loss_trend":              trend,
    }


# ── Alerts ─────────────────────────────────────────────────────────────────────

def _build_loss_alerts(metrics: dict[str, Any]) -> list[dict[str, str]]:
    alerts: list[dict[str, str]] = []

    net_loss = metrics.get("total_net_loss", 0)
    if net_loss > 500_000 * 100:         # > $500k
        alerts.append({
            "level": "critical",
            "message": (
                f"Total net operational loss ${net_loss / 100:,.0f} — "
                "review risk controls and escalate to board."
            ),
        })
    elif net_loss > 100_000 * 100:       # > $100k
        alerts.append({
            "level": "warning",
            "message": f"Operational losses ${net_loss / 100:,.0f} — monitor trends closely.",
        })

    if metrics.get("open_events", 0) > 3:
        alerts.append({
            "level": "warning",
            "message": (
                f"{metrics['open_events']} loss events still open/unresolved — "
                "resolution backlog may mask ongoing exposure."
            ),
        })

    if metrics.get("loss_trend") == "worsening":
        alerts.append({
            "level": "warning",
            "message": "Loss frequency/volume is trending upward — investigate root causes.",
        })

    recovery_rate = metrics.get("recovery_rate", 1.0)
    if recovery_rate < 0.20 and net_loss > 50_000 * 100:
        alerts.append({
            "level": "info",
            "message": (
                f"Recovery rate {recovery_rate:.0%} — consider insurance or contractual "
                "recovery mechanisms to reduce net exposure."
            ),
        })

    return alerts


# ── Narrative ──────────────────────────────────────────────────────────────────

async def _generate_loss_narrative(metrics: dict[str, Any], settings: Any) -> str:
    total     = metrics.get("total_events", 0)
    net_loss  = metrics.get("total_net_loss", 0)
    rec_rate  = metrics.get("recovery_rate", 0)
    trend     = metrics.get("loss_trend", "stable")
    open_ev   = metrics.get("open_events", 0)

    lines = [
        f"{total} operational loss events recorded; total net loss ${net_loss / 100:,.0f}.",
        f"Recovery rate {rec_rate:.0%}; trend is {trend}.",
    ]
    if open_ev:
        lines.append(f"{open_ev} event(s) remain unresolved.")
    return " ".join(lines)


# ── Node ───────────────────────────────────────────────────────────────────────

async def run_loss_agent(state: RiskState, config: dict) -> dict[str, Any]:
    """Risk Loss Events Skill Agent — done_when: state['losses']['total_events'] is int."""
    logs: list[RiskStepLog] = state.get("logs") or []
    result: dict[str, Any] = {"losses": None, "logs": logs, "error": None}

    try:
        rows    = _parse_loss_csv(state.get("loss_csv") or "")
        metrics = _compute_loss_metrics(rows)
        alerts  = _build_loss_alerts(metrics)
        narr    = await _generate_loss_narrative(metrics, config.get("settings"))

        result["losses"] = {**metrics, "alerts": alerts, "narrative": narr}
        logs.append(RiskStepLog(
            node="loss_agent", status="completed",
            message=f"Processed {len(rows)} loss events",
            metrics={
                "total_net_loss":  metrics["total_net_loss"],
                "loss_trend":      metrics["loss_trend"],
            },
        ))
    except Exception as exc:
        result["error"] = f"loss_agent failed: {exc}"
        logs.append(RiskStepLog(node="loss_agent", status="failed", message=str(exc)))

    return result
