"""A negotiation answer needs the company's figures, or it says it has none.

With no HR data the hiring answer assumed 30 000 TRY a month and 15% turnover;
with no technology data the budget answer assumed 50 000 TRY a month and 15%
infrastructure waste, then told the company how many liras it could safely cut.
Both now decline and say what to connect.
"""
from __future__ import annotations

from app.services.agent_negotiation import CHRONegotiationResponder, CTONegotiationResponder


def test_hiring_plan_without_hr_data_declines():
    out = CHRONegotiationResponder().build_hiring_plan_response({}, runway_months=8)
    assert out["durum"] == "veri_yok"
    assert "maaş" in out["eksik"]
    assert "monthly_hire_cost_try" not in out


def test_hiring_plan_uses_the_figures_given():
    out = CHRONegotiationResponder().build_hiring_plan_response(
        {"open_critical_roles": 2, "avg_monthly_salary_try": 40_000, "annual_turnover_rate": 0.25},
        runway_months=12,
    )
    assert out["durum"] == "hesaplandi"
    assert out["planned_hires"] == 2
    assert out["monthly_hire_cost_try"] == round(2 * 40_000 * 1.225)
    assert out["attrition_risk"] == "high"


def test_budget_cut_without_technology_data_declines():
    out = CTONegotiationResponder().build_budget_cut_response({})
    assert out["durum"] == "veri_yok"
    assert "teknoloji" in out["eksik"]
    assert "savings_try" not in out


def test_budget_cut_marks_the_velocity_figure_as_a_rule():
    out = CTONegotiationResponder().build_budget_cut_response(
        {"monthly_tech_budget_try": 100_000, "infra_waste_pct": 0.2, "overall_health_score": 5.0}
    )
    assert out["durum"] == "hesaplandi"
    assert out["savings_try"] == round(100_000 * 0.2 + 100_000 * 0.05)
    assert out["velocity_olcum"] == "kural"
    assert out["tech_health_risk"] == "high"
