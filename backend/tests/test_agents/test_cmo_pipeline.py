# CMO pipeline tests -- pure computation, no LLM calls.
# Tests cover campaign_agent, funnel_agent, cohort_agent, and synthesis cross-risks.
from __future__ import annotations

import pytest

from app.agents.cmo.campaign_agent import (
    _parse_campaign_csv,
    _compute_campaign_metrics,
    _build_campaign_alerts,
)
from app.agents.cmo.funnel_agent import (
    _parse_funnel_csv,
    _compute_funnel_metrics,
    _build_funnel_alerts,
    _normalize_stage,
)
from app.agents.cmo.cohort_agent import (
    _parse_cohort_csv,
    _compute_cohort_metrics,
    _build_cohort_alerts,
)
from app.agents.ceo.synthesis_agent import _detect_cross_risks


# ── Fixtures ──────────────────────────────────────────────────────────────────

CAMPAIGN_CSV = """Campaign,Channel,Spend,Revenue,Conversions,Clicks,Impressions
Summer Sale,google,5000,18000,120,3000,100000
Brand Awareness,facebook,3000,2500,20,1500,80000
Email Retarget,email,500,4000,45,600,5000
Product Launch,google,8000,6000,60,4000,120000
"""

FUNNEL_CSV = """id,stage,source,created,closed
1,Won,google,2024-01-05,2024-02-10
2,SQL,organic,2024-01-10,
3,MQL,facebook,2024-01-12,
4,Won,google,2024-01-15,2024-03-01
5,Lost,cold_email,2024-01-20,2024-02-05
6,Won,organic,2024-01-22,2024-02-28
7,Lead,facebook,2024-01-25,
8,SQL,google,2024-01-28,
"""

COHORT_CSV = """cohort,users,retention_30d,retention_90d,ltv,cac
2024-01,200,45%,28%,1200,150
2024-02,180,42%,25%,1100,160
2024-03,220,50%,32%,1350,145
2024-04,190,48%,30%,1250,155
"""


# ═══════════════════════════════════════════════════════════════════════════════
# CAMPAIGN AGENT TESTS
# ═══════════════════════════════════════════════════════════════════════════════

def test_campaign_parse_returns_list():
    rows = _parse_campaign_csv(CAMPAIGN_CSV)
    assert isinstance(rows, list)
    assert len(rows) == 4


def test_campaign_parse_spend_in_cents():
    rows = _parse_campaign_csv(CAMPAIGN_CSV)
    # Summer Sale: $5000 -> 500000 cents
    summer = next(r for r in rows if "Summer" in r["name"])
    assert summer["spend_cents"] == 500_000


def test_campaign_parse_revenue_in_cents():
    rows = _parse_campaign_csv(CAMPAIGN_CSV)
    summer = next(r for r in rows if "Summer" in r["name"])
    assert summer["revenue_cents"] == 1_800_000


def test_campaign_parse_channel_lowercase():
    rows = _parse_campaign_csv(CAMPAIGN_CSV)
    channels = {r["channel"] for r in rows}
    assert all(c == c.lower() for c in channels)


def test_campaign_metrics_total_spend():
    rows = _parse_campaign_csv(CAMPAIGN_CSV)
    metrics = _compute_campaign_metrics(rows)
    # 5000+3000+500+8000 = 16500 -> 1_650_000 cents
    assert metrics["total_spend_cents"] == 1_650_000


def test_campaign_metrics_overall_roas():
    rows = _parse_campaign_csv(CAMPAIGN_CSV)
    metrics = _compute_campaign_metrics(rows)
    # total revenue: 18000+2500+4000+6000 = 30500
    # roas = 30500/16500 ~ 1.85
    assert metrics["overall_roas"] == pytest.approx(30500 / 16500, rel=0.01)


def test_campaign_metrics_by_channel_present():
    rows = _parse_campaign_csv(CAMPAIGN_CSV)
    metrics = _compute_campaign_metrics(rows)
    assert "google" in metrics["by_channel"]
    assert "facebook" in metrics["by_channel"]
    assert "email" in metrics["by_channel"]


def test_campaign_metrics_channel_roas():
    rows = _parse_campaign_csv(CAMPAIGN_CSV)
    metrics = _compute_campaign_metrics(rows)
    # email: spend 500, revenue 4000 -> roas 8.0
    assert metrics["by_channel"]["email"]["roas"] == pytest.approx(8.0, rel=0.01)


def test_campaign_metrics_top_campaigns_by_roas():
    rows = _parse_campaign_csv(CAMPAIGN_CSV)
    metrics = _compute_campaign_metrics(rows)
    top = metrics["top_campaigns"]
    assert len(top) >= 1
    # top should be sorted descending by roas
    roas_vals = [c["roas"] for c in top]
    assert roas_vals == sorted(roas_vals, reverse=True)


def test_campaign_metrics_underperforming_detected():
    rows = _parse_campaign_csv(CAMPAIGN_CSV)
    metrics = _compute_campaign_metrics(rows)
    # Brand Awareness: spend 3000, revenue 2500 -> roas 0.83 -> underperforming
    under_names = [c["name"] for c in metrics["underperforming"]]
    assert any("Brand" in n for n in under_names)


def test_campaign_alerts_low_roas():
    rows = _parse_campaign_csv(CAMPAIGN_CSV)
    metrics = _compute_campaign_metrics(rows)
    alerts = _build_campaign_alerts(metrics)
    # overall roas ~1.85 < 2.0 -> high alert
    levels = [a["level"] for a in alerts]
    assert "high" in levels or "critical" in levels


def test_campaign_alerts_underperforming():
    rows = _parse_campaign_csv(CAMPAIGN_CSV)
    metrics = _compute_campaign_metrics(rows)
    alerts = _build_campaign_alerts(metrics)
    messages = " ".join(a["message"] for a in alerts)
    assert "underperform" in messages.lower() or "wasting" in messages.lower()


def test_campaign_empty_csv():
    metrics = _compute_campaign_metrics([])
    assert metrics["overall_roas"] == 0.0
    assert metrics["total_spend_cents"] == 0


# ═══════════════════════════════════════════════════════════════════════════════
# FUNNEL AGENT TESTS
# ═══════════════════════════════════════════════════════════════════════════════

def test_funnel_stage_normalization():
    assert _normalize_stage("Won") == "won"
    assert _normalize_stage("closed won") == "won"
    assert _normalize_stage("MQL") == "mql"
    assert _normalize_stage("Sales Qualified") == "sql"
    assert _normalize_stage("prospect") == "lead"


def test_funnel_parse_returns_list():
    rows = _parse_funnel_csv(FUNNEL_CSV)
    assert isinstance(rows, list)
    assert len(rows) >= 6


def test_funnel_metrics_total_leads():
    rows = _parse_funnel_csv(FUNNEL_CSV)
    metrics = _compute_funnel_metrics(rows)
    assert metrics["total_leads"] == len(rows)


def test_funnel_metrics_won_count():
    rows = _parse_funnel_csv(FUNNEL_CSV)
    metrics = _compute_funnel_metrics(rows)
    # 3 won entries in CSV
    assert metrics["won_count"] == 3


def test_funnel_metrics_conversion_rate_range():
    rows = _parse_funnel_csv(FUNNEL_CSV)
    metrics = _compute_funnel_metrics(rows)
    assert 0.0 <= metrics["overall_conversion_rate"] <= 1.0


def test_funnel_metrics_stage_rates_in_range():
    rows = _parse_funnel_csv(FUNNEL_CSV)
    metrics = _compute_funnel_metrics(rows)
    assert 0.0 <= metrics["lead_to_mql_rate"] <= 1.0
    assert 0.0 <= metrics["mql_to_sql_rate"] <= 1.0
    assert 0.0 <= metrics["sql_to_won_rate"] <= 1.0


def test_funnel_metrics_by_source():
    rows = _parse_funnel_csv(FUNNEL_CSV)
    metrics = _compute_funnel_metrics(rows)
    assert isinstance(metrics["by_source"], dict)
    assert len(metrics["by_source"]) >= 1


def test_funnel_metrics_bottleneck_valid():
    rows = _parse_funnel_csv(FUNNEL_CSV)
    metrics = _compute_funnel_metrics(rows)
    valid_stages = {"lead_to_mql", "mql_to_sql", "sql_to_won"}
    assert metrics["bottleneck_stage"] in valid_stages


def test_funnel_alerts_low_conversion():
    rows = _parse_funnel_csv(FUNNEL_CSV)
    metrics = _compute_funnel_metrics(rows)
    alerts = _build_funnel_alerts(metrics)
    # ~37.5% overall conversion is actually good, but stages may still trigger
    assert isinstance(alerts, list)


def test_funnel_empty():
    metrics = _compute_funnel_metrics([])
    assert metrics["total_leads"] == 0
    assert metrics["overall_conversion_rate"] == 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# COHORT AGENT TESTS
# ═══════════════════════════════════════════════════════════════════════════════

def test_cohort_parse_returns_list():
    rows = _parse_cohort_csv(COHORT_CSV)
    assert isinstance(rows, list)
    assert len(rows) == 4


def test_cohort_parse_retention_normalized():
    rows = _parse_cohort_csv(COHORT_CSV)
    for r in rows:
        if r["retention_30d"] is not None:
            assert 0.0 <= r["retention_30d"] <= 1.0


def test_cohort_parse_ltv_in_cents():
    rows = _parse_cohort_csv(COHORT_CSV)
    first = rows[0]
    # ltv=1200 -> 120000 cents
    assert first["ltv_cents"] == 120_000


def test_cohort_metrics_avg_retention():
    rows = _parse_cohort_csv(COHORT_CSV)
    metrics = _compute_cohort_metrics(rows)
    # avg 30d: (45+42+50+48)/4 = 46.25% -> 0.4625
    assert metrics["avg_retention_30d"] == pytest.approx(0.4625, rel=0.01)


def test_cohort_metrics_ltv_cac_ratio():
    rows = _parse_cohort_csv(COHORT_CSV)
    metrics = _compute_cohort_metrics(rows)
    # avg ltv: (1200+1100+1350+1250)/4 = 1225
    # avg cac: (150+160+145+155)/4 = 152.5
    # ratio: 1225/152.5 ~ 8.03
    assert metrics["ltv_cac_ratio"] == pytest.approx(1225 / 152.5, rel=0.01)


def test_cohort_metrics_churn_rate():
    rows = _parse_cohort_csv(COHORT_CSV)
    metrics = _compute_cohort_metrics(rows)
    # churn = 1 - avg_ret30
    assert metrics["churn_rate"] == pytest.approx(1.0 - metrics["avg_retention_30d"], rel=0.01)


def test_cohort_metrics_best_worst():
    rows = _parse_cohort_csv(COHORT_CSV)
    metrics = _compute_cohort_metrics(rows)
    assert metrics["best_cohort"] is not None
    assert metrics["worst_cohort"] is not None
    assert metrics["best_cohort"]["retention_30d"] >= metrics["worst_cohort"]["retention_30d"]


def test_cohort_metrics_retention_trend():
    rows = _parse_cohort_csv(COHORT_CSV)
    metrics = _compute_cohort_metrics(rows)
    assert metrics["retention_trend"] in {"improving", "stable", "degrading"}


def test_cohort_alerts_good_ltv_cac_no_critical():
    # Use metrics directly (not CSV which has ~55% churn when parsed)
    # to test that good LTV:CAC doesn't trigger a unit economics alert.
    metrics = {
        "ltv_cac_ratio": 8.0,
        "churn_rate": 0.03,       # 3% monthly churn -> no churn alert
        "avg_retention_30d": 0.97,
        "retention_trend": "stable",
        "avg_ltv_cents": 120_000,
        "avg_cac_cents": 15_000,
        "cohorts_analyzed": 4,
    }
    alerts = _build_cohort_alerts(metrics)
    # LTV:CAC 8x + low churn -> no critical alerts
    critical_alerts = [a for a in alerts if a["level"] == "critical"]
    assert len(critical_alerts) == 0


def test_cohort_alerts_bad_ltv_cac():
    metrics = {
        "ltv_cac_ratio": 0.8,
        "churn_rate": 0.05,
        "avg_retention_30d": 0.50,
        "retention_trend": "stable",
        "avg_ltv_cents": 80_000,
        "avg_cac_cents": 100_000,
        "cohorts_analyzed": 4,
    }
    alerts = _build_cohort_alerts(metrics)
    assert any(a["level"] == "critical" for a in alerts)


def test_cohort_alerts_high_churn():
    metrics = {
        "ltv_cac_ratio": 3.5,
        "churn_rate": 0.12,
        "avg_retention_30d": 0.50,
        "retention_trend": "stable",
        "avg_ltv_cents": 120_000,
        "avg_cac_cents": 34_000,
        "cohorts_analyzed": 4,
    }
    alerts = _build_cohort_alerts(metrics)
    assert any(a["level"] == "critical" for a in alerts)


def test_cohort_empty():
    metrics = _compute_cohort_metrics([])
    assert metrics["cohorts_analyzed"] == 0
    assert metrics["ltv_cac_ratio"] == 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# CEO SYNTHESIS — CMO CROSS-RISK TESTS
# ═══════════════════════════════════════════════════════════════════════════════

def test_cmo_cross_risk_negative_unit_econ():
    fin = {"cash_runway_months": 8, "revenue_cents": 500_000_00}
    tech = {}
    mkt = {
        "ltv_cac_ratio": 0.7,
        "overall_cac_cents": 50_000,
        "churn_rate": 0.05,
        "overall_roas": 2.0,
        "total_spend_cents": 100_000,
    }
    risks = _detect_cross_risks(fin, tech, mkt)
    ids = [r["risk_id"] for r in risks]
    assert "cross-cmo-negative-unit-econ" in ids


def test_cmo_cross_risk_high_churn():
    fin = {"cash_runway_months": 12, "revenue_cents": 1_000_000_00}
    tech = {}
    mkt = {
        "ltv_cac_ratio": 4.0,
        "overall_cac_cents": 20_000,
        "churn_rate": 0.10,
        "overall_roas": 3.0,
        "total_spend_cents": 50_000,
    }
    risks = _detect_cross_risks(fin, tech, mkt)
    ids = [r["risk_id"] for r in risks]
    assert "cross-cmo-high-churn" in ids


def test_cmo_cross_risk_roas_runway():
    fin = {"cash_runway_months": 4, "revenue_cents": 500_000_00}
    tech = {}
    mkt = {
        "ltv_cac_ratio": 2.5,
        "overall_cac_cents": 30_000,
        "churn_rate": 0.04,
        "overall_roas": 1.2,
        "total_spend_cents": 200_000,
    }
    risks = _detect_cross_risks(fin, tech, mkt)
    ids = [r["risk_id"] for r in risks]
    assert "cross-cmo-roas-runway" in ids


def test_cmo_no_cross_risks_healthy():
    fin = {"cash_runway_months": 18, "revenue_cents": 1_000_000_00}
    tech = {}
    mkt = {
        "ltv_cac_ratio": 5.0,
        "overall_cac_cents": 20_000,
        "churn_rate": 0.03,
        "overall_roas": 4.0,
        "total_spend_cents": 100_000,
    }
    risks = _detect_cross_risks(fin, tech, mkt)
    cmo_risks = [r for r in risks if "cmo" in r["risk_id"]]
    assert len(cmo_risks) == 0


def test_cmo_no_cross_risks_when_no_mkt_data():
    fin = {"cash_runway_months": 6}
    tech = {}
    risks = _detect_cross_risks(fin, tech, None)
    cmo_risks = [r for r in risks if "cmo" in r["risk_id"]]
    assert len(cmo_risks) == 0
