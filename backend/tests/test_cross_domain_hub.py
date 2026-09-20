"""Çapraz bulgular yalnızca gerçekten analiz edilmiş alanlardan doğar.

The hub used to fill every missing metric with a flattering default — tech
health 7, ROAS 2.5, SLA 95%, runway 12 months — score the company on them, and
raise insights about domains it had no data for.
"""
from __future__ import annotations

from app.agents.orchestration.cross_domain_hub import CrossDomainHub


def test_no_domain_data_means_no_score_and_no_insight() -> None:
    r = CrossDomainHub(pnl={"revenue": 100, "net_margin": 0.1}).run()
    assert r.analyzed_domains == []
    assert r.insights == []
    assert r.overall_health_score is None, "tek bileşenle (CFO) skor uydurulmamalı"
    assert "hiçbir alan" in r.executive_summary


def test_an_insight_needs_every_metric_it_rests_on() -> None:
    """Runway alone must not produce the talent-cash insight."""
    r = CrossDomainHub(forecast={"scenarios": {"base": {"runway_months": 2}}}).run()
    assert r.insights == []


def test_unknown_runway_is_not_twelve_months() -> None:
    assert CrossDomainHub().runway_months is None


def test_real_results_produce_insights_with_named_evidence() -> None:
    chro = {"attrition": {"total_departures": 5}, "headcount": {"total_headcount": 10},
            "chro_summary": {"chro_health_score": 4.0}}
    r = CrossDomainHub(
        domain_results={"chro": chro},
        forecast={"scenarios": {"base": {"runway_months": 3}}},
    ).run()
    assert r.metrics["ayrilma_orani"] == 0.5
    [ins] = r.insights
    assert ins.id == "talent_cash_cascade"
    assert any("İK dosyası" in e for e in ins.evidence)
    assert ins.financial_impact_try is None


def test_health_lists_its_components_and_needs_two() -> None:
    one = CrossDomainHub(domain_results={"coo": {"coo_summary": {"overall_ops_score": 6.0}}}).run()
    assert one.overall_health_score is None and len(one.health_components) == 1
    two = CrossDomainHub(domain_results={
        "coo": {"coo_summary": {"overall_ops_score": 6.0}},
        "audit": {"audit_summary": {"audit_health_score": 80.0}},
    }).run()
    assert two.overall_health_score == 70.0
    assert {c["alan"] for c in two.health_components} == {"coo", "audit"}


def test_critical_findings_come_from_the_uploaded_lists() -> None:
    r = CrossDomainHub(domain_results={"compliance": {"violations": {"critical_open": 2}}}).run()
    [ins] = r.insights
    assert ins.id == "regulatory_exposure" and ins.domains == ["compliance"]
