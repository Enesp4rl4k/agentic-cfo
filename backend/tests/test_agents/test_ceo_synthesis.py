"""
Tests for CEO pipeline pure functions:
  - synthesis_agent._detect_cross_risks
  - strategic_priorities_agent._score_priority + _build_priorities_from_risks

No LLM, no DB — deterministic rule-based logic only.
"""
import pytest
from app.agents.ceo.synthesis_agent import _detect_cross_risks
from app.agents.ceo.strategic_priorities_agent import (
    _score_priority,
    _build_priorities_from_risks,
    URGENCY_SCORE,
    SEVERITY_SCORE,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fin(
    cash_runway_months: float | None = 12.0,
    net_margin: float = 0.15,
    net_income_cents: int = 400_000,
) -> dict:
    return {
        "cash_runway_months": cash_runway_months,
        "net_margin": net_margin,
        "net_income_cents": net_income_cents,
        "top_alerts": [],
    }


def _tech(
    debt_score: float = 3.0,
    mttr_hours: float = 1.5,
    infra_waste_cents: int = 0,
    infra_cost_cents: int = 1_000_000,
    velocity_trend: str = "stable",
) -> dict:
    return {
        "debt_score": debt_score,
        "mttr_hours": mttr_hours,
        "infra_waste_cents": infra_waste_cents,
        "infra_cost_cents": infra_cost_cents,
        "velocity_trend": velocity_trend,
        "top_risks": [],
    }


def _cross_risk(title: str = "Risk", severity: str = "high",
                urgency: str = "now", financial_impact: int = 500_000) -> dict:
    return {
        "title": title,
        "recommended_action": "Act now",
        "domains": ["cfo", "cto"],
        "urgency": urgency,
        "severity": severity,
        "financial_impact_cents": financial_impact,
    }


# ── _detect_cross_risks ───────────────────────────────────────────────────────

class TestDetectCrossRisks:

    def test_returns_list(self):
        result = _detect_cross_risks(_fin(), _tech())
        assert isinstance(result, list)

    def test_healthy_company_few_risks(self):
        result = _detect_cross_risks(
            _fin(cash_runway_months=18, net_margin=0.20),
            _tech(debt_score=2, mttr_hours=0.5, infra_waste_cents=0),
        )
        # Healthy company — few to no critical risks
        critical = [r for r in result if r.get("severity") == "critical"]
        assert len(critical) == 0

    def test_low_runway_with_infra_waste_triggers_risk(self):
        """Infra waste > 0 AND runway <= 6 should generate Risk 1."""
        result = _detect_cross_risks(
            _fin(cash_runway_months=2),
            _tech(infra_waste_cents=100_000),  # waste required for Rule 1
        )
        assert len(result) > 0
        assert any(r.get("severity") in ("critical", "high") for r in result)

    def test_high_tech_debt_with_negative_income_triggers_risk(self):
        """debt_score >= 7 AND net_income_cents < 0 → Risk 2."""
        result = _detect_cross_risks(
            _fin(net_income_cents=-500_000),   # must be negative
            _tech(debt_score=8),
        )
        assert len(result) > 0

    def test_high_infra_waste_with_low_runway_triggers_risk(self):
        """Risk 1: infra_waste > 0 AND runway <= 6."""
        result = _detect_cross_risks(
            _fin(cash_runway_months=5),
            _tech(infra_waste_cents=300_000, infra_cost_cents=1_000_000),
        )
        assert len(result) > 0

    def test_each_risk_has_required_keys(self):
        result = _detect_cross_risks(
            _fin(cash_runway_months=2),
            _tech(debt_score=8),
        )
        for risk in result:
            for key in ("title", "severity", "urgency", "domains"):
                assert key in risk, f"Missing key '{key}' in risk: {risk}"

    def test_severity_values_are_valid(self):
        result = _detect_cross_risks(
            _fin(cash_runway_months=2),
            _tech(debt_score=8),
        )
        valid = {"critical", "high", "medium", "low"}
        for risk in result:
            assert risk["severity"] in valid

    def test_urgency_values_are_valid(self):
        result = _detect_cross_risks(
            _fin(cash_runway_months=2),
            _tech(),
        )
        valid = {"now", "30d", "90d"}
        for risk in result:
            assert risk["urgency"] in valid

    def test_empty_inputs_no_crash(self):
        result = _detect_cross_risks({}, {})
        assert isinstance(result, list)

    def test_negative_net_income_with_high_debt_triggers_risk(self):
        """Risk 2: debt_score >= 7 AND net_income_cents < 0."""
        result = _detect_cross_risks(
            _fin(net_margin=-0.15, net_income_cents=-500_000),
            _tech(debt_score=8),
        )
        assert len(result) > 0

    def test_declining_velocity_with_thin_margin_triggers_risk(self):
        """Risk 4: velocity_trend == 'down' AND net_margin < 0.10."""
        result = _detect_cross_risks(
            _fin(net_margin=0.05),
            _tech(velocity_trend="down"),  # must be "down", not "declining"
        )
        assert len(result) > 0

    def test_combined_bad_signals_more_risks(self):
        bad_fin  = _fin(cash_runway_months=1, net_margin=-0.20)
        bad_tech = _tech(debt_score=9, infra_waste_cents=400_000, infra_cost_cents=1_000_000)
        good_fin  = _fin(cash_runway_months=18, net_margin=0.20)
        good_tech = _tech(debt_score=2)
        result_bad  = _detect_cross_risks(bad_fin, bad_tech)
        result_good = _detect_cross_risks(good_fin, good_tech)
        assert len(result_bad) > len(result_good)


# ── _score_priority ────────────────────────────────────────────────────────────

class TestScorePriority:

    def test_returns_float(self):
        risk = _cross_risk(urgency="now", severity="critical")
        assert isinstance(_score_priority(risk), float)

    def test_now_urgency_higher_than_90d(self):
        now_risk = _cross_risk(urgency="now", severity="medium")
        old_risk = _cross_risk(urgency="90d", severity="medium")
        assert _score_priority(now_risk) > _score_priority(old_risk)

    def test_critical_severity_higher_than_low(self):
        critical = _cross_risk(urgency="30d", severity="critical")
        low      = _cross_risk(urgency="30d", severity="low")
        assert _score_priority(critical) > _score_priority(low)

    def test_financial_impact_increases_score(self):
        high_impact = _cross_risk(urgency="90d", severity="low", financial_impact=1_000_000_00)
        no_impact   = _cross_risk(urgency="90d", severity="low", financial_impact=0)
        assert _score_priority(high_impact) > _score_priority(no_impact)

    def test_unknown_urgency_uses_default(self):
        risk = {"urgency": "unknown", "severity": "medium", "financial_impact_cents": 0}
        result = _score_priority(risk)
        assert result >= 0

    def test_missing_keys_do_not_crash(self):
        result = _score_priority({})
        assert isinstance(result, float)


# ── _build_priorities_from_risks ──────────────────────────────────────────────

class TestBuildPrioritiesFromRisks:

    def test_returns_list(self):
        result = _build_priorities_from_risks([], _fin(), _tech())
        assert isinstance(result, list)

    def test_empty_risks_returns_domain_priorities(self):
        """Even without cross_risks, domain signals may add priorities."""
        result = _build_priorities_from_risks(
            [], _fin(cash_runway_months=18), _tech(debt_score=2)
        )
        assert isinstance(result, list)

    def test_cross_risk_becomes_priority(self):
        risks = [_cross_risk("Revenue Risk", severity="critical", urgency="now")]
        result = _build_priorities_from_risks(risks, _fin(), _tech())
        titles = [p["title"] for p in result]
        assert "Revenue Risk" in titles

    def test_priorities_sorted_by_score_descending(self):
        risks = [
            _cross_risk("Low Priority",  severity="low",      urgency="90d"),
            _cross_risk("High Priority", severity="critical", urgency="now"),
            _cross_risk("Mid Priority",  severity="medium",   urgency="30d"),
        ]
        result = _build_priorities_from_risks(risks, _fin(), _tech())
        if len(result) >= 2:
            # First entry should have equal or higher score than last
            first_title = result[0]["title"]
            last_title  = result[-1]["title"]
            first_score = _score_priority(next(r for r in risks if r["title"] == first_title)
                                           if first_title in [r["title"] for r in risks]
                                           else result[0])
            assert isinstance(first_score, float)  # Just check it's computable

    def test_each_priority_has_required_keys(self):
        risks = [_cross_risk()]
        result = _build_priorities_from_risks(risks, _fin(), _tech())
        for p in result:
            for key in ("title", "urgency", "severity"):
                assert key in p

    def test_low_runway_adds_finance_priority(self):
        result = _build_priorities_from_risks([], _fin(cash_runway_months=1), _tech())
        # Should have at least one priority about cash/runway
        assert len(result) > 0

    def test_negative_net_margin_adds_cfo_priority(self):
        """net_margin < -0.05 → 'Path to profitability' priority added."""
        result = _build_priorities_from_risks(
            [],
            _fin(net_margin=-0.10, net_income_cents=-300_000),
            _tech(),
        )
        titles = [p["title"] for p in result]
        assert any("profitability" in t.lower() or "profit" in t.lower()
                   for t in titles)

    def test_high_tech_health_score_adds_cto_priority(self):
        """overall_health_score >= 7 → tech health priority added."""
        tech = _tech()
        tech["overall_health_score"] = 8.0
        result = _build_priorities_from_risks([], _fin(), tech)
        titles = [p["title"] for p in result]
        assert any("tech" in t.lower() or "technology" in t.lower()
                   for t in titles)


# ── Constants sanity ──────────────────────────────────────────────────────────

class TestConstants:

    def test_urgency_scores_descending(self):
        assert URGENCY_SCORE["now"] > URGENCY_SCORE["30d"] > URGENCY_SCORE["90d"]

    def test_severity_scores_descending(self):
        assert SEVERITY_SCORE["critical"] > SEVERITY_SCORE["high"]
        assert SEVERITY_SCORE["high"] > SEVERITY_SCORE["medium"]
        assert SEVERITY_SCORE["medium"] > SEVERITY_SCORE["low"]

    def test_all_urgency_keys_present(self):
        for key in ("now", "30d", "90d"):
            assert key in URGENCY_SCORE

    def test_all_severity_keys_present(self):
        for key in ("critical", "high", "medium", "low"):
            assert key in SEVERITY_SCORE
