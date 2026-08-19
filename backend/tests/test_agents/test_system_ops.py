"""Unit tests for system ops helpers — deterministic, no DB/Redis required."""

from __future__ import annotations

from app.api.system import (
    ERROR_BUDGETS,
    OPS_SCHEMA_VERSION,
    SLA_ANALYZING_BREACH_MINUTES,
    _derive_actions,
    _percentile,
    _safe_pct,
)


def test_safe_pct_zero_denominator() -> None:
    assert _safe_pct(5, 0) == 0.0


def test_safe_pct_rounds() -> None:
    assert _safe_pct(1, 4) == 25.0


def test_percentile_empty() -> None:
    assert _percentile([], 95.0) is None


def test_percentile_single_value() -> None:
    assert _percentile([4200], 95.0) == 4200


def test_percentile_p95() -> None:
    values = list(range(1, 101))
    assert _percentile(values, 95.0) == 95


def test_derive_actions_stable_when_healthy() -> None:
    actions = _derive_actions(failed_count=0, awaiting_review_count=0, breaches=[])
    assert len(actions) == 1
    assert "stable" in actions[0].lower()


def test_derive_actions_failed_jobs() -> None:
    actions = _derive_actions(failed_count=3, awaiting_review_count=0, breaches=[])
    assert any("failed" in a.lower() for a in actions)


def test_derive_actions_awaiting_review() -> None:
    actions = _derive_actions(failed_count=0, awaiting_review_count=2, breaches=[])
    assert any("awaiting_review" in a.lower() for a in actions)


def test_derive_actions_sla_breach_escalation() -> None:
    breaches = [{"job_id": "abc", "age_minutes": 20}]
    actions = _derive_actions(failed_count=0, awaiting_review_count=0, breaches=breaches)
    assert any("escalate" in a.lower() for a in actions)


def test_derive_actions_capped_at_three() -> None:
    breaches = [{"job_id": "x", "age_minutes": 30}]
    actions = _derive_actions(failed_count=5, awaiting_review_count=4, breaches=breaches)
    assert len(actions) <= 3


def test_ops_schema_version() -> None:
    assert OPS_SCHEMA_VERSION == "v1.1"


def test_sla_breach_threshold() -> None:
    assert SLA_ANALYZING_BREACH_MINUTES == 15


def test_error_budgets_cover_core_domains() -> None:
    assert set(ERROR_BUDGETS) >= {"analysis", "chat", "sync"}
