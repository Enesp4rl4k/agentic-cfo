"""Summarise canonical engineering signals into a CTO-kernel-ready shape.

Bridges the Connector Platform (`canonical_eng_signals`) to the CTO view: when a
connector has populated real signals, this produces the `existing_cto_data` dict
the CTO kernel treats as measured data (`data_source="real"`), instead of the
CFO-financials × benchmark extrapolation.
"""
from __future__ import annotations

import statistics
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.canonical_eng_signal import CanonicalEngSignal

DEFAULT_WINDOW_DAYS = 30


def _aware(dt: datetime) -> datetime:
    """SQLite hands back naive datetimes even for tz=True columns."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


async def summarize_eng_signals(
    org_id: str, db: AsyncSession, *, window_days: int = DEFAULT_WINDOW_DAYS
) -> dict[str, Any] | None:
    """Return a raw metrics summary, or None if the org has no signals."""
    since = datetime.now(UTC) - timedelta(days=window_days)
    rows = (
        await db.execute(
            select(CanonicalEngSignal).where(
                CanonicalEngSignal.org_id == org_id,
                CanonicalEngSignal.occurred_at >= since,
            )
        )
    ).scalars().all()
    if not rows:
        return None

    commits = [r for r in rows if r.signal_type == "commit"]
    prs = [r for r in rows if r.signal_type == "pull_request"]
    incidents = [r for r in rows if r.signal_type == "incident"]
    issues = [r for r in rows if r.signal_type == "issue"]

    active_days = len({_aware(r.occurred_at).date() for r in commits})
    code_churn = sum(r.magnitude or 0 for r in commits)
    merged_prs = [r for r in prs if (r.attributes or {}).get("merged")]
    cycle_hours = [r.magnitude for r in merged_prs if isinstance(r.magnitude, int)]
    median_cycle = statistics.median(cycle_hours) if cycle_hours else None

    # Velocity trend: commit count in the recent half vs the earlier half.
    midpoint = since + timedelta(days=window_days / 2)
    recent = sum(1 for r in commits if _aware(r.occurred_at) >= midpoint)
    earlier = sum(1 for r in commits if _aware(r.occurred_at) < midpoint)
    if earlier == 0:
        trend = "stable" if recent == 0 else "improving"
    elif recent >= earlier * 1.15:
        trend = "improving"
    elif recent <= earlier * 0.85:
        trend = "deteriorating"
    else:
        trend = "stable"

    return {
        "source": "github",
        "window_days": window_days,
        "commit_count": len(commits),
        "active_dev_days": active_days,
        "code_churn_lines": code_churn,
        "pr_count": len(prs),
        "pr_merged_count": len(merged_prs),
        "median_pr_cycle_hours": median_cycle,
        "incident_count": len(incidents),
        "issue_count": len(issues),
        "velocity_trend": trend,
    }


def to_cto_existing_data(summary: dict[str, Any]) -> dict[str, Any]:
    """Map the raw summary onto the `existing_cto_data` contract the CTO kernel
    reads (`velocity_trend`, `overall_health_score`, `tech_debt_score`, …)."""
    window = summary.get("window_days") or DEFAULT_WINDOW_DAYS
    incidents = summary.get("incident_count", 0)
    cycle_h = summary.get("median_pr_cycle_hours")
    active_days = summary.get("active_dev_days", 0)

    # Health: fewer incidents + faster PR cycle + steady cadence → higher.
    health = 7.5
    health -= min(4.0, incidents * 0.6)  # each incident/mo stings
    if cycle_h is not None:
        health -= min(2.5, max(0.0, (cycle_h - 24) / 48))  # >1 day cycle time drags
    health += min(1.5, active_days / window * 3)  # working most days helps
    health = round(max(1.0, min(10.0, health)), 1)

    # Tech-debt proxy: slow PR cycle + high churn per active day.
    churn_per_day = (summary.get("code_churn_lines", 0) / active_days) if active_days else 0
    debt = 3.0
    if cycle_h is not None:
        debt += min(3.0, max(0.0, (cycle_h - 24) / 36))
    debt += min(3.0, churn_per_day / 800)
    debt = round(max(1.0, min(9.0, debt)), 1)

    return {
        "_source": summary.get("source", "connector"),
        "velocity_trend": summary.get("velocity_trend", "stable"),
        "overall_health_score": health,
        "tech_debt_score": debt,
        "commit_count_30d": summary.get("commit_count", 0),
        "pr_count_30d": summary.get("pr_count", 0),
        "incident_count_30d": incidents,
        "median_pr_cycle_hours": cycle_h,
        "active_dev_days": active_days,
    }


async def cto_existing_data_from_signals(
    org_id: str, db: AsyncSession, *, window_days: int = DEFAULT_WINDOW_DAYS
) -> dict[str, Any] | None:
    summary = await summarize_eng_signals(org_id, db, window_days=window_days)
    return to_cto_existing_data(summary) if summary else None
