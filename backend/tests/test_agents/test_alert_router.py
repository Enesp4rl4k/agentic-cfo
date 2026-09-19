"""
Tests for app.services.alert_router — AlertRouter

Pure business logic: no DB, no I/O, no mocks needed.
All tests are synchronous.

Coverage targets:
  - Deduplication (within TTL / outside TTL)
  - Aggregation threshold
  - Escalation (critical level / high priority score)
  - Routing (normal warning → ROUTE)
  - Priority scoring (keyword boost)
  - build_digest output structure
  - Empty inputs
  - Edge cases (empty history, single alert, all suppressed)
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.services.alert_router import (
    AlertAction,
    AlertDecision,
    AlertRouter,
    RawAlert,
    _compute_priority,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────

def _alert(
    level: str = "warning",
    message: str = "Test alert",
    domain: str = "cfo",
    source: str = "cashflow",
    job_id: str = "job-001",
    ts: datetime | None = None,
) -> RawAlert:
    return RawAlert(
        level=level,
        message=message,
        domain=domain,
        source=source,
        job_id=job_id,
        timestamp=ts or datetime.now(UTC),
    )


# ── Priority scoring ──────────────────────────────────────────────────────────

class TestComputePriority:
    def test_critical_base_score(self):
        a = _alert(level="critical", message="Generic critical")
        assert _compute_priority(a) == 1.0  # critical base = 1.0, capped at 1.0

    def test_warning_base_score(self):
        a = _alert(level="warning", message="No keywords here")
        score = _compute_priority(a)
        assert score == 0.5

    def test_info_base_score(self):
        a = _alert(level="info", message="Just info")
        assert _compute_priority(a) == pytest.approx(0.1)

    def test_keyword_boost_runway(self):
        a = _alert(level="warning", message="Runway is 3 months")
        score = _compute_priority(a)
        # warning(0.5) + runway(0.3) = 0.8
        assert score == pytest.approx(0.8)

    def test_keyword_boost_cash(self):
        a = _alert(level="warning", message="Cash position declining")
        score = _compute_priority(a)
        # warning(0.5) + cash(0.2) = 0.7
        assert score == pytest.approx(0.7)

    def test_keyword_boost_nakit_turkish(self):
        a = _alert(level="warning", message="Nakit pozisyonu kritik")
        score = _compute_priority(a)
        # warning(0.5) + nakit(0.2) + kritik(0.15) = 0.85
        assert score == pytest.approx(0.85)

    def test_score_capped_at_one(self):
        a = _alert(level="critical", message="fraud runway cash nakit critical kritik breach outage churn duplicate")
        score = _compute_priority(a)
        assert score <= 1.0

    def test_unknown_level_defaults_to_info(self):
        a = _alert(level="unknown_level", message="test")
        score = _compute_priority(a)
        assert score == pytest.approx(0.1)


# ── Deduplication ─────────────────────────────────────────────────────────────

class TestDeduplication:
    def test_suppress_duplicate_within_ttl(self):
        router = AlertRouter(dedup_ttl_hours=4)
        a = _alert(message="Runway is 3 months")
        # Same alert in history 2 hours ago
        history = [_alert(
            message="Runway is 3 months",
            ts=datetime.now(UTC) - timedelta(hours=2),
        )]
        decisions = router.process_alerts([a], history)
        assert len(decisions) == 1
        assert decisions[0].action == AlertAction.SUPPRESS

    def test_allow_duplicate_outside_ttl(self):
        router = AlertRouter(dedup_ttl_hours=4)
        a = _alert(message="Runway is 3 months")
        # Same alert in history 5 hours ago (outside 4h TTL)
        history = [_alert(
            message="Runway is 3 months",
            ts=datetime.now(UTC) - timedelta(hours=5),
        )]
        decisions = router.process_alerts([a], history)
        assert len(decisions) == 1
        assert decisions[0].action != AlertAction.SUPPRESS

    def test_different_fingerprint_not_suppressed(self):
        router = AlertRouter()
        a = _alert(message="Different message about cash")
        history = [_alert(message="Something else entirely")]
        decisions = router.process_alerts([a], history)
        assert decisions[0].action != AlertAction.SUPPRESS

    def test_empty_history_never_suppresses(self):
        router = AlertRouter()
        alerts = [_alert(message=f"Alert {i}") for i in range(3)]
        decisions = router.process_alerts(alerts, [])
        assert all(d.action != AlertAction.SUPPRESS for d in decisions)

    def test_suppress_reason_contains_time(self):
        router = AlertRouter()
        a = _alert(message="Duplicate test")
        history = [_alert(
            message="Duplicate test",
            ts=datetime.now(UTC) - timedelta(hours=1),
        )]
        decisions = router.process_alerts([a], history)
        assert "UTC" in decisions[0].reason


# ── Aggregation ───────────────────────────────────────────────────────────────

class TestAggregation:
    def test_aggregate_when_threshold_met(self):
        # threshold=3 → 3+ alerts of same domain+level → AGGREGATE
        router = AlertRouter(aggregation_threshold=3)
        alerts = [
            _alert(message=f"Warning {i}", domain="cfo", level="warning")
            for i in range(3)
        ]
        decisions = router.process_alerts(alerts)
        aggregate_count = sum(1 for d in decisions if d.action == AlertAction.AGGREGATE)
        assert aggregate_count >= 1

    def test_no_aggregate_below_threshold(self):
        router = AlertRouter(aggregation_threshold=5)
        alerts = [
            _alert(message=f"Warning {i}", domain="cfo", level="warning")
            for i in range(2)
        ]
        decisions = router.process_alerts(alerts)
        # With only 2 alerts and threshold=5, no aggregation
        assert all(d.action != AlertAction.AGGREGATE for d in decisions)

    def test_different_domains_not_aggregated(self):
        router = AlertRouter(aggregation_threshold=2)
        alerts = [
            _alert(domain="cfo", level="warning", message="CFO warning"),
            _alert(domain="cto", level="warning", message="CTO warning"),
        ]
        decisions = router.process_alerts(alerts)
        assert all(d.action != AlertAction.AGGREGATE for d in decisions)


# ── Escalation ────────────────────────────────────────────────────────────────

class TestEscalation:
    def test_critical_alert_always_escalates(self):
        router = AlertRouter(escalate_threshold=0.75)
        a = _alert(level="critical", message="System failure")
        decisions = router.process_alerts([a])
        assert decisions[0].action == AlertAction.ESCALATE

    def test_high_priority_escalates(self):
        router = AlertRouter(escalate_threshold=0.75)
        # warning(0.5) + runway(0.3) = 0.8 > 0.75 → ESCALATE
        a = _alert(level="warning", message="Runway is below 3 months")
        decisions = router.process_alerts([a])
        assert decisions[0].action == AlertAction.ESCALATE

    def test_escalated_routes_to_exec_team(self):
        router = AlertRouter()
        a = _alert(level="critical", message="Critical cash failure")
        decisions = router.process_alerts([a])
        assert len(decisions[0].route_to) > 0
        # Exec team always included in escalation
        route_to = decisions[0].route_to
        assert any("ceo" in r or "cfo" in r for r in route_to)

    def test_critical_channel_is_sms_or_email(self):
        router = AlertRouter()
        a = _alert(level="critical", message="Critical")
        decisions = router.process_alerts([a])
        assert "email" in decisions[0].channel or "sms" in decisions[0].channel


# ── Routing ───────────────────────────────────────────────────────────────────

class TestRouting:
    def test_low_priority_warning_routes_to_domain_owner(self):
        router = AlertRouter(escalate_threshold=0.9)  # high threshold
        a = _alert(level="warning", message="Minor cost increase", domain="cfo")
        decisions = router.process_alerts([a])
        assert decisions[0].action == AlertAction.ROUTE

    def test_route_uses_domain_owner(self):
        router = AlertRouter(escalate_threshold=0.9)
        a = _alert(level="warning", message="Minor issue", domain="cto")
        decisions = router.process_alerts([a])
        d = decisions[0]
        assert d.action == AlertAction.ROUTE
        assert any("cto" in r for r in d.route_to)

    def test_route_channel_is_slack(self):
        router = AlertRouter(escalate_threshold=0.9)
        a = _alert(level="warning", message="Minor issue")
        decisions = router.process_alerts([a])
        assert decisions[0].channel == "slack"

    def test_unknown_domain_falls_back_to_owner(self):
        router = AlertRouter(escalate_threshold=0.9)
        a = _alert(level="warning", message="Issue", domain="unknown_dept")
        decisions = router.process_alerts([a])
        assert decisions[0].action == AlertAction.ROUTE
        assert len(decisions[0].route_to) > 0


# ── Sorting ───────────────────────────────────────────────────────────────────

class TestSorting:
    def test_decisions_sorted_by_priority_descending(self):
        router = AlertRouter()
        alerts = [
            _alert(level="info",     message="Low priority info"),
            _alert(level="critical", message="Critical runway issue"),
            _alert(level="warning",  message="Standard warning"),
        ]
        decisions = router.process_alerts(alerts)
        scores = [d.priority_score for d in decisions]
        assert scores == sorted(scores, reverse=True)


# ── Edge cases ────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_empty_alerts_returns_empty(self):
        router = AlertRouter()
        decisions = router.process_alerts([])
        assert decisions == []

    def test_empty_alerts_empty_history(self):
        router = AlertRouter()
        decisions = router.process_alerts([], [])
        assert decisions == []

    def test_all_duplicates_returns_all_suppressed(self):
        router = AlertRouter()
        msg = "Duplicate alert"
        history = [_alert(message=msg, ts=datetime.now(UTC) - timedelta(hours=1))]
        alerts = [_alert(message=msg) for _ in range(3)]
        decisions = router.process_alerts(alerts, history)
        # All three are duplicates
        assert all(d.action == AlertAction.SUPPRESS for d in decisions)

    def test_fingerprint_stable_across_instances(self):
        a1 = _alert(message="Same message", domain="cfo", source="cashflow")
        a2 = _alert(message="Same message", domain="cfo", source="cashflow")
        assert a1.fingerprint == a2.fingerprint

    def test_different_source_different_fingerprint(self):
        a1 = _alert(message="Same message", domain="cfo", source="cashflow")
        a2 = _alert(message="Same message", domain="cfo", source="forecast")
        # source not in fingerprint — only domain + source_field + message[:80]
        # both have same domain+message, source IS in fingerprint via RawAlert.fingerprint
        # fingerprint = domain:source:message[:80]
        assert a1.fingerprint != a2.fingerprint

    def test_single_alert_no_aggregation(self):
        router = AlertRouter(aggregation_threshold=3)
        a = _alert(level="warning", message="Single warning")
        decisions = router.process_alerts([a])
        assert decisions[0].action != AlertAction.AGGREGATE


# ── build_digest ──────────────────────────────────────────────────────────────

class TestBuildDigest:
    def test_digest_has_required_keys(self):
        router = AlertRouter()
        alerts = [
            _alert(level="critical", message="Critical issue"),
            _alert(level="warning",  message="Warning issue"),
        ]
        decisions = router.process_alerts(alerts)
        digest = router.build_digest(decisions)
        assert "total" in digest
        assert "actionable" in digest

    def test_digest_total_matches_decisions(self):
        router = AlertRouter()
        alerts = [_alert(message=f"Alert {i}") for i in range(4)]
        decisions = router.process_alerts(alerts)
        digest = router.build_digest(decisions)
        assert digest["total"] == len(decisions)

    def test_digest_empty_decisions(self):
        router = AlertRouter()
        digest = router.build_digest([])
        assert digest["total"] == 0
        assert digest["actionable"] == 0

    def test_actionable_count_correct(self):
        router = AlertRouter()
        alerts = [
            _alert(level="critical", message="Critical"),         # ESCALATE (actionable)
            _alert(level="warning",  message="Low priority"),     # ROUTE (actionable)
        ]
        decisions = router.process_alerts(alerts)
        digest = router.build_digest(decisions)
        # ESCALATE + ROUTE are both actionable
        actionable = sum(1 for d in decisions if d.is_actionable)
        assert digest["actionable"] == actionable


# ── AlertDecision.is_actionable ───────────────────────────────────────────────

class TestIsActionable:
    def test_route_is_actionable(self):
        d = AlertDecision(action=AlertAction.ROUTE, alert=_alert())
        assert d.is_actionable is True

    def test_escalate_is_actionable(self):
        d = AlertDecision(action=AlertAction.ESCALATE, alert=_alert())
        assert d.is_actionable is True

    def test_suppress_not_actionable(self):
        d = AlertDecision(action=AlertAction.SUPPRESS, alert=_alert())
        assert d.is_actionable is False

    def test_aggregate_not_actionable(self):
        d = AlertDecision(action=AlertAction.AGGREGATE, alert=_alert())
        assert d.is_actionable is False
