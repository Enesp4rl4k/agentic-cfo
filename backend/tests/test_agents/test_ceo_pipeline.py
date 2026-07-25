# CEO pipeline tests — pure computation, no LLM calls.
#
# Tests cover:
#   - SynthesisAgent: cross-risk detection rules
#   - StrategicPrioritiesAgent: priority ranking from cross-risks
#   - BoardDeckAgent: slide generation, one-page summary
#   - CondenseSummaries: CFO/CTO output extraction helpers
#   - API helper: overall_health_score calculation

import pytest

from app.agents.ceo.synthesis_agent import (
    _detect_cross_risks,
    _condense_financial_summary,
    _condense_tech_summary,
)
from app.agents.ceo.strategic_priorities_agent import (
    _build_priorities_from_risks,
    _score_priority,
)
from app.agents.ceo.board_deck_agent import (
    _build_slides,
    _build_one_page_summary,
)
from app.api.ceo import _compute_overall_health


# ── Shared fixtures ───────────────────────────────────────────────────────────

HEALTHY_FIN = {
    "revenue_cents": 1_000_000,
    "net_income_cents": 200_000,
    "net_margin": 0.20,
    "gross_margin": 0.55,
    "cash_runway_months": 18,
    "monthly_burn_cents": 80_000,
    "cash_flow_net_cents": 120_000,
    "forecast_base_12m_cents": 2_400_000,
    "top_alerts": [],
    "narrative": "Strong performance.",
}

STRESSED_FIN = {
    "revenue_cents": 500_000,
    "net_income_cents": -80_000,
    "net_margin": -0.16,
    "gross_margin": 0.30,
    "cash_runway_months": 3,
    "monthly_burn_cents": 180_000,
    "cash_flow_net_cents": -80_000,
    "forecast_base_12m_cents": -960_000,
    "top_alerts": [{"level": "critical", "message": "Cash runway < 3 months"}],
    "narrative": "Cash at risk.",
}

HEALTHY_TECH = {
    "overall_health_score": 2.0,
    "infra_cost_cents": 200_000,
    "infra_waste_cents": 0,
    "debt_score": 1.5,
    "mttr_hours": 0.5,
    "sla_breach_pct": 2.0,
    "avg_velocity": 40,
    "velocity_trend": "up",
    "top_risks": [],
    "narrative": "Tech health excellent.",
}

AT_RISK_TECH = {
    "overall_health_score": 7.5,
    "infra_cost_cents": 800_000,
    "infra_waste_cents": 250_000,
    "debt_score": 8.0,
    "mttr_hours": 10.0,
    "sla_breach_pct": 35.0,
    "avg_velocity": 20,
    "velocity_trend": "down",
    "top_risks": [{"severity": "critical", "message": "MTTR exceeded SLA", "domain": "Reliability"}],
    "narrative": "Multiple tech risks.",
}

CROSS_RISKS_SAMPLE = [
    {
        "risk_id": "cross-infra-cash-runway",
        "title": "Cloud waste accelerating cash burn",
        "domains": ["cfo", "cto"],
        "severity": "critical",
        "financial_impact_cents": 250_000,
        "tech_impact": "None",
        "recommended_action": "Cut cloud waste immediately.",
        "urgency": "now",
    },
    {
        "risk_id": "cross-debt-revenue",
        "title": "Tech debt slowing revenue delivery",
        "domains": ["cfo", "cto"],
        "severity": "high",
        "financial_impact_cents": 80_000,
        "tech_impact": "Debt score 8/10",
        "recommended_action": "Allocate 20% eng to debt reduction.",
        "urgency": "30d",
    },
]


# ── SynthesisAgent tests ──────────────────────────────────────────────────────

def test_no_cross_risks_when_healthy():
    risks = _detect_cross_risks(HEALTHY_FIN, HEALTHY_TECH)
    assert risks == []


def test_infra_cash_runway_risk_detected():
    risks = _detect_cross_risks(STRESSED_FIN, AT_RISK_TECH)
    ids = [r["risk_id"] for r in risks]
    assert "cross-infra-cash-runway" in ids


def test_debt_revenue_risk_detected():
    fin = {**STRESSED_FIN, "cash_runway_months": 12}  # runway ok, but negative income
    risks = _detect_cross_risks(fin, AT_RISK_TECH)
    ids = [r["risk_id"] for r in risks]
    assert "cross-debt-revenue" in ids


def test_mttr_revenue_risk_detected():
    fin = {**HEALTHY_FIN}
    tech = {**HEALTHY_TECH, "mttr_hours": 9.0}
    risks = _detect_cross_risks(fin, tech)
    ids = [r["risk_id"] for r in risks]
    assert "cross-mttr-revenue" in ids


def test_velocity_margin_risk_detected():
    fin = {**HEALTHY_FIN, "net_margin": 0.05}
    tech = {**HEALTHY_TECH, "velocity_trend": "down"}
    risks = _detect_cross_risks(fin, tech)
    ids = [r["risk_id"] for r in risks]
    assert "cross-velocity-margin" in ids


def test_dual_critical_risk_detected():
    fin = {
        **STRESSED_FIN,
        "top_alerts": [{"level": "critical", "message": "Cash critical"}],
    }
    tech = {
        **AT_RISK_TECH,
        "top_risks": [{"severity": "critical", "message": "Infra down", "domain": "Infra"}],
    }
    risks = _detect_cross_risks(fin, tech)
    ids = [r["risk_id"] for r in risks]
    assert "cross-dual-critical" in ids


def test_risks_sorted_by_urgency():
    risks = _detect_cross_risks(STRESSED_FIN, AT_RISK_TECH)
    urgencies = [r.get("urgency") for r in risks]
    order = {"now": 0, "30d": 1, "90d": 2}
    scores = [order.get(u, 2) for u in urgencies]
    assert scores == sorted(scores)


# ── CondenseSummaries helpers tests ───────────────────────────────────────────

def test_condense_financial_has_required_keys():
    fake_cfo_state = {
        "pnl": {
            "revenue": 1_000_000,
            "net_income": 200_000,
            "net_margin": 0.20,
            "gross_margin": 0.55,
            "narrative": "Good.",
        },
        "cashflow": {
            "operating": 300_000,
            "net_change": 150_000,
            "monthly_series": [
                {"month": "2024-01", "in": 500_000, "out": 350_000, "net": 150_000},
            ],
            "alerts": [],
        },
        "forecast": {
            "scenarios": {"base": {"twelve_month_net": 1_800_000, "runway_months": 18}},
            "alerts": [],
        },
    }
    summary = _condense_financial_summary(fake_cfo_state)
    required = ["revenue_cents", "net_income_cents", "net_margin", "cash_runway_months"]
    for key in required:
        assert key in summary, f"Missing key: {key}"


def test_condense_tech_has_required_keys():
    fake_cto_state = {
        "infra": {"total_cost_cents": 200_000, "waste_estimate_cents": 10_000},
        "tech_debt": {"debt_score": 3.0},
        "incidents": {"mttr_hours": 1.5, "sla_breach_pct": 5.0},
        "velocity": {"avg_velocity": 35, "velocity_trend": "flat"},
        "cto_summary": {
            "overall_health_score": 2.5,
            "top_risks": [],
            "narrative": "Healthy.",
        },
    }
    summary = _condense_tech_summary(fake_cto_state)
    required = ["overall_health_score", "infra_cost_cents", "debt_score", "mttr_hours"]
    for key in required:
        assert key in summary, f"Missing key: {key}"


# ── StrategicPrioritiesAgent tests ────────────────────────────────────────────

def test_priority_score_now_higher_than_30d():
    now_risk = {"urgency": "now", "severity": "high", "financial_impact_cents": 100_000,
                "effort": "low", "impact": "high"}
    later_risk = {"urgency": "30d", "severity": "high", "financial_impact_cents": 100_000,
                  "effort": "low", "impact": "high"}
    assert _score_priority(now_risk) > _score_priority(later_risk)


def test_priority_score_critical_higher_than_medium():
    critical = {"urgency": "30d", "severity": "critical", "financial_impact_cents": 50_000,
                "effort": "medium", "impact": "critical"}
    medium = {"urgency": "30d", "severity": "medium", "financial_impact_cents": 50_000,
              "effort": "medium", "impact": "medium"}
    assert _score_priority(critical) > _score_priority(medium)


def test_build_priorities_returns_list():
    priorities = _build_priorities_from_risks(CROSS_RISKS_SAMPLE, HEALTHY_FIN, HEALTHY_TECH)
    assert isinstance(priorities, list)
    assert len(priorities) > 0


def test_build_priorities_ranked():
    priorities = _build_priorities_from_risks(CROSS_RISKS_SAMPLE, STRESSED_FIN, AT_RISK_TECH)
    ranks = [p["rank"] for p in priorities]
    assert ranks == list(range(1, len(ranks) + 1))


def test_build_priorities_has_required_fields():
    """Priorities use 'title', 'rationale', 'urgency', 'domains', 'owner_role' (not 'action'/'domain')."""
    priorities = _build_priorities_from_risks(CROSS_RISKS_SAMPLE, HEALTHY_FIN, HEALTHY_TECH)
    for p in priorities:
        assert "rank" in p
        assert "title" in p
        assert "urgency" in p
        assert "domains" in p        # list e.g. ["cfo", "cto"]
        assert "owner_role" in p     # e.g. "CEO", "CFO", "CTO"


def test_build_priorities_empty_risks():
    priorities = _build_priorities_from_risks([], HEALTHY_FIN, HEALTHY_TECH)
    assert isinstance(priorities, list)


# ── BoardDeckAgent tests ──────────────────────────────────────────────────────

def test_build_slides_returns_list():
    # _build_slides(fin, tech, cross_risks, priorities, period)
    slides = _build_slides(HEALTHY_FIN, HEALTHY_TECH, CROSS_RISKS_SAMPLE, [], "2024-Q2")
    assert isinstance(slides, list)


def test_build_slides_count():
    slides = _build_slides(HEALTHY_FIN, HEALTHY_TECH, CROSS_RISKS_SAMPLE, [], "2024-Q2")
    # Expect at least 4 slides (done_when criterion)
    assert len(slides) >= 4


def test_build_slides_have_required_fields():
    """_build_slides returns dicts with slide_number, title, chart_type, key_metrics/narrative."""
    slides = _build_slides(HEALTHY_FIN, HEALTHY_TECH, CROSS_RISKS_SAMPLE, [], "2024-Q2")
    for slide in slides:
        assert "slide_number" in slide
        assert "title" in slide
        assert "chart_type" in slide      # actual field name (not "type")
        assert "narrative" in slide       # actual field name (not "content")


def test_build_slides_numbers_sequential():
    slides = _build_slides(HEALTHY_FIN, HEALTHY_TECH, CROSS_RISKS_SAMPLE, [], "2024-Q2")
    numbers = [s["slide_number"] for s in slides]
    assert numbers == list(range(1, len(numbers) + 1))


def test_build_one_page_summary_is_string():
    priorities = _build_priorities_from_risks(CROSS_RISKS_SAMPLE, STRESSED_FIN, AT_RISK_TECH)
    # _build_one_page_summary(fin, tech, cross_risks, priorities, period, company_name)
    summary = _build_one_page_summary(
        STRESSED_FIN, AT_RISK_TECH, CROSS_RISKS_SAMPLE, priorities,
        "2024-Q2", "TestCo"
    )
    assert isinstance(summary, str)
    assert len(summary) > 50


def test_build_one_page_summary_contains_key_terms():
    priorities = _build_priorities_from_risks(CROSS_RISKS_SAMPLE, STRESSED_FIN, AT_RISK_TECH)
    summary = _build_one_page_summary(
        STRESSED_FIN, AT_RISK_TECH, CROSS_RISKS_SAMPLE, priorities,
        "2024-Q2", "TestCo"
    )
    lower = summary.lower()
    assert any(term in lower for term in ["revenue", "risk", "action", "priority", "tech", "financial"])


# ── API overall_health_score tests ────────────────────────────────────────────

def test_overall_health_healthy_company():
    result = {
        "financial_summary": HEALTHY_FIN,
        "tech_summary": HEALTHY_TECH,
    }
    score = _compute_overall_health(result)
    assert score is not None
    assert score >= 70.0, f"Healthy company should score >= 70, got {score}"


def test_overall_health_stressed_company():
    result = {
        "financial_summary": STRESSED_FIN,
        "tech_summary": AT_RISK_TECH,
    }
    score = _compute_overall_health(result)
    assert score is not None
    assert score < 70.0, f"Stressed company should score < 70, got {score}"


def test_overall_health_fin_only():
    result = {"financial_summary": HEALTHY_FIN}
    score = _compute_overall_health(result)
    assert score is not None
    assert 0.0 <= score <= 100.0


def test_overall_health_tech_only():
    result = {"tech_summary": HEALTHY_TECH}
    score = _compute_overall_health(result)
    assert score is not None
    assert 0.0 <= score <= 100.0


def test_overall_health_none_when_no_data():
    score = _compute_overall_health({})
    assert score is None


def test_overall_health_range():
    for fin, tech in [
        (HEALTHY_FIN, HEALTHY_TECH),
        (STRESSED_FIN, AT_RISK_TECH),
        (HEALTHY_FIN, AT_RISK_TECH),
        (STRESSED_FIN, HEALTHY_TECH),
    ]:
        score = _compute_overall_health({"financial_summary": fin, "tech_summary": tech})
        assert score is not None
        assert 0.0 <= score <= 100.0, f"Score out of range: {score}"
