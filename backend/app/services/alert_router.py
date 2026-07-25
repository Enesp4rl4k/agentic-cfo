"""
Smart Alert Router — Phase 5.1

Eliminates alert fatigue by:
1. Deduplication  — suppress identical alerts seen within TTL window
2. Aggregation    — group similar alerts into a single summary
3. Severity score — rank by business_impact × urgency
4. Routing        — decide: SUPPRESS / AGGREGATE / ROUTE / ESCALATE

This is pure business logic — no I/O, no LLM calls, fully testable.

Usage:
    router = AlertRouter()
    decisions = router.process_alerts(raw_alerts, recent_history)
    # decisions: list of AlertDecision
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class AlertAction(StrEnum):
    SUPPRESS   = "suppress"    # Duplicate — drop
    AGGREGATE  = "aggregate"   # Group with similar alerts
    ROUTE      = "route"       # Send to domain owner
    ESCALATE   = "escalate"    # Critical — send to executives


@dataclass
class RawAlert:
    """Incoming alert from any pipeline agent."""
    level:     str          # critical | warning | info
    message:   str
    domain:    str          # cfo | cto | chro | cmo | coo | audit | risk
    source:    str          # cashflow | forecast | anomaly | ...
    job_id:    str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    evidence:  dict[str, Any] = field(default_factory=dict)

    @property
    def fingerprint(self) -> str:
        """Stable hash for deduplication — domain + source + first 80 chars of message."""
        key = f"{self.domain}:{self.source}:{self.message[:80]}"
        return hashlib.md5(key.encode()).hexdigest()[:12]  # noqa: S324 — non-security use


@dataclass
class AlertDecision:
    action:        AlertAction
    alert:         RawAlert
    grouped_with:  list[RawAlert] = field(default_factory=list)
    priority_score: float = 0.0
    route_to:      list[str] = field(default_factory=list)
    channel:       str = "dashboard"  # dashboard | slack | email | sms
    reason:        str = ""

    @property
    def is_actionable(self) -> bool:
        return self.action in (AlertAction.ROUTE, AlertAction.ESCALATE)


# ── Severity → numeric impact ──────────────────────────────────────────────

_SEVERITY_SCORE: dict[str, float] = {
    "critical": 1.0,
    "warning":  0.5,
    "info":     0.1,
}

# Domain → default owner role
_DOMAIN_OWNERS: dict[str, list[str]] = {
    "cfo":        ["cfo@company.com"],
    "cto":        ["cto@company.com"],
    "chro":       ["chro@company.com"],
    "cmo":        ["cmo@company.com"],
    "coo":        ["coo@company.com"],
    "audit":      ["audit@company.com", "cfo@company.com"],
    "risk":       ["cro@company.com", "ceo@company.com"],
    "compliance": ["compliance@company.com"],
}

_EXEC_TEAM: list[str] = ["ceo@company.com", "cfo@company.com"]


def _compute_priority(alert: RawAlert) -> float:
    """
    Priority score = severity_weight × urgency_multiplier.

    Urgency multiplier: alerts with financial keywords score higher.
    Returns 0.0 – 1.0 (higher = more urgent).
    """
    base = _SEVERITY_SCORE.get(alert.level, 0.1)

    # Keyword-based urgency boost
    urgency_keywords = [
        ("runway", 0.3),
        ("cash", 0.2),
        ("nakit", 0.2),
        ("critical", 0.15),
        ("kritik", 0.15),
        ("breach", 0.2),
        ("outage", 0.25),
        ("churn", 0.15),
        ("fraud", 0.3),
        ("duplicate", 0.2),
    ]
    boost = sum(
        b for kw, b in urgency_keywords
        if kw.lower() in alert.message.lower()
    )

    return min(1.0, base + boost)


class AlertRouter:
    """
    Stateless alert routing engine.

    Call process_alerts() with the new alerts and recent history.
    History is used for deduplication (seen within TTL window).
    """

    def __init__(
        self,
        dedup_ttl_hours: int = 4,
        aggregation_threshold: int = 3,
        escalate_threshold: float = 0.75,
    ) -> None:
        self.dedup_ttl      = timedelta(hours=dedup_ttl_hours)
        self.agg_threshold  = aggregation_threshold
        self.esc_threshold  = escalate_threshold

    def process_alerts(
        self,
        new_alerts: list[RawAlert],
        recent_history: list[RawAlert] | None = None,
    ) -> list[AlertDecision]:
        """
        Process a batch of new alerts against recent history.

        Args:
            new_alerts:     Alerts from the current pipeline run
            recent_history: Previously seen alerts (last N hours, from DB or cache)

        Returns:
            List of AlertDecision — one per new_alert (may be SUPPRESS)
        """
        history = recent_history or []
        now = datetime.now(timezone.utc)

        # Build dedup index from history
        seen_fingerprints: dict[str, datetime] = {}
        for h in history:
            seen_fingerprints[h.fingerprint] = h.timestamp

        # Group new alerts by domain+level for aggregation check
        domain_level_groups: dict[str, list[RawAlert]] = {}
        for a in new_alerts:
            key = f"{a.domain}:{a.level}"
            domain_level_groups.setdefault(key, []).append(a)

        decisions: list[AlertDecision] = []

        for alert in new_alerts:
            fp = alert.fingerprint
            priority = _compute_priority(alert)

            # ── 1. Deduplication ─────────────────────────────────────────────
            if fp in seen_fingerprints:
                last_seen = seen_fingerprints[fp]
                if (now - last_seen) < self.dedup_ttl:
                    decisions.append(AlertDecision(
                        action=AlertAction.SUPPRESS,
                        alert=alert,
                        priority_score=priority,
                        reason=f"Duplicate — last seen {last_seen.strftime('%H:%M')} UTC",
                    ))
                    continue

            # ── 2. Aggregation ───────────────────────────────────────────────
            key = f"{alert.domain}:{alert.level}"
            siblings = [a for a in domain_level_groups.get(key, []) if a is not alert]
            if len(siblings) >= self.agg_threshold - 1:
                decisions.append(AlertDecision(
                    action=AlertAction.AGGREGATE,
                    alert=alert,
                    grouped_with=siblings,
                    priority_score=priority,
                    route_to=_DOMAIN_OWNERS.get(alert.domain, []),
                    channel="dashboard",
                    reason=(
                        f"Aggregated with {len(siblings)} similar {alert.domain} alerts. "
                        f"Showing as group to reduce noise."
                    ),
                ))
                continue

            # ── 3. Escalate vs. Route ────────────────────────────────────────
            if priority >= self.esc_threshold or alert.level == "critical":
                channel = "sms+email" if alert.level == "critical" else "email"
                decisions.append(AlertDecision(
                    action=AlertAction.ESCALATE,
                    alert=alert,
                    priority_score=priority,
                    route_to=_EXEC_TEAM + _DOMAIN_OWNERS.get(alert.domain, []),
                    channel=channel,
                    reason=f"Priority {priority:.2f} ≥ threshold {self.esc_threshold}",
                ))
            else:
                decisions.append(AlertDecision(
                    action=AlertAction.ROUTE,
                    alert=alert,
                    priority_score=priority,
                    route_to=_DOMAIN_OWNERS.get(alert.domain, ["owner@company.com"]),
                    channel="slack",
                    reason=f"Routed to domain owner ({alert.domain})",
                ))

        # Sort by priority descending
        decisions.sort(key=lambda d: -d.priority_score)
        return decisions

    def build_digest(
        self,
        decisions: list[AlertDecision],
    ) -> dict[str, Any]:
        """
        Build a structured digest from routing decisions.
        Used by Phase 5.2 (alert digest endpoint).

        Returns:
            {
              "critical": [...],   # ESCALATE decisions
              "high": [...],       # ROUTE decisions with priority > 0.5
              "aggregated": [...], # AGGREGATE groups
              "suppressed_count": int,
              "total_actionable": int,
              "top_action": str,
            }
        """
        critical:    list[dict] = []
        high:        list[dict] = []
        aggregated:  list[dict] = []
        suppressed   = 0

        for d in decisions:
            item = {
                "level":          d.alert.level,
                "domain":         d.alert.domain,
                "message":        d.alert.message,
                "priority_score": round(d.priority_score, 2),
                "route_to":       d.route_to,
                "channel":        d.channel,
                "job_id":         d.alert.job_id,
                "timestamp":      d.alert.timestamp.isoformat(),
            }
            if d.action == AlertAction.SUPPRESS:
                suppressed += 1
            elif d.action == AlertAction.ESCALATE:
                critical.append(item)
            elif d.action == AlertAction.AGGREGATE:
                item["group_size"] = len(d.grouped_with) + 1
                aggregated.append(item)
            else:
                if d.priority_score > 0.5:
                    high.append(item)

        actionable_count = len(critical) + len(high) + len(aggregated)

        top_action = "Kritik uyarı yok."
        if critical:
            top_action = critical[0]["message"]
        elif high:
            top_action = high[0]["message"]

        return {
            "critical":         critical,
            "high":             high,
            "aggregated":       aggregated,
            "suppressed_count": suppressed,
            "total_actionable": actionable_count,
            "top_action":       top_action,
        }
