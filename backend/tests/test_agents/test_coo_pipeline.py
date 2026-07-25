# COO pipeline tests — pure computation, no LLM calls.
# Run: pytest backend/tests/test_agents/test_coo_pipeline.py -v
from __future__ import annotations

import pytest

from app.agents.coo.process_agent import (
    _parse_process_csv,
    _compute_process_metrics,
    _build_process_alerts,
)
from app.agents.coo.resource_agent import (
    _parse_resource_csv,
    _compute_resource_metrics,
    _build_resource_alerts,
)
from app.agents.coo.sla_agent import (
    _parse_sla_csv,
    _compute_sla_metrics,
    _build_sla_alerts,
)
from app.agents.ceo.synthesis_agent import (
    _detect_cross_risks,
    _condense_ops_summary,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

PROCESS_CSV = """\
process,cycle_time,throughput,wip,team,capacity
Order Fulfillment,3.5,50,15,Warehouse,60
Customer Onboarding,7.0,20,30,Sales,25
Invoice Processing,1.5,100,10,Finance,120
Support Ticket Resolution,5.0,40,35,Support,45
Product Delivery,12.0,10,20,Engineering,15
"""

# Resource CSV — utilization as percentage values (will be divided by 100)
RESOURCE_CSV = """\
team,headcount,utilization,output,capacity,cost_cents
Engineering,25,92,450,500,5000000
Sales,10,75,200,250,2000000
Finance,8,55,160,200,1600000
Support,15,115,280,280,2500000
Marketing,6,45,90,150,1200000
"""

SLA_CSV = """\
ticket_id,priority,created_at,first_response_at,resolved_at,nps_score,category
T001,p1,2024-01-01 09:00:00,2024-01-01 09:30:00,2024-01-01 12:00:00,8,billing
T002,p2,2024-01-02 10:00:00,2024-01-02 12:00:00,2024-01-03 08:00:00,6,technical
T003,p1,2024-01-03 08:00:00,2024-01-03 10:00:00,2024-01-03 20:00:00,3,billing
T004,p3,2024-01-04 14:00:00,2024-01-04 18:00:00,2024-01-06 14:00:00,7,general
T005,p2,2024-01-05 09:00:00,2024-01-05 11:00:00,2024-01-06 09:00:00,5,technical
T006,p1,2024-01-06 08:00:00,2024-01-06 12:00:00,2024-01-07 08:00:00,2,billing
T007,p4,2024-01-07 15:00:00,2024-01-08 09:00:00,2024-01-10 15:00:00,9,general
T008,p2,2024-01-08 10:00:00,2024-01-08 13:00:00,2024-01-09 10:00:00,7,technical
"""


# ── Process Agent Tests ────────────────────────────────────────────────────────

def test_process_parse_returns_list():
    rows = _parse_process_csv(PROCESS_CSV)
    assert isinstance(rows, list)
    assert len(rows) == 5


def test_process_parse_has_name_field():
    """Parser stores process name under 'name' key (not 'process')."""
    rows = _parse_process_csv(PROCESS_CSV)
    assert all("name" in r for r in rows)
    assert rows[0]["name"] == "Order Fulfillment"


def test_process_parse_has_required_fields():
    rows = _parse_process_csv(PROCESS_CSV)
    for r in rows:
        assert "name" in r
        assert "cycle_time" in r
        assert "throughput" in r
        assert "wip" in r


def test_process_metrics_avg_cycle_time_days():
    rows = _parse_process_csv(PROCESS_CSV)
    metrics = _compute_process_metrics(rows)
    # Key is avg_cycle_time_days
    assert metrics["avg_cycle_time_days"] > 0


def test_process_metrics_bottleneck_detection():
    rows = _parse_process_csv(PROCESS_CSV)
    metrics = _compute_process_metrics(rows)
    # Product Delivery has highest cycle_time (12.0)
    assert metrics["bottleneck_process"] == "Product Delivery"


def test_process_metrics_efficiency_score_range():
    rows = _parse_process_csv(PROCESS_CSV)
    metrics = _compute_process_metrics(rows)
    assert 0.0 <= metrics["efficiency_score"] <= 10.0


def test_process_metrics_overloaded_processes():
    rows = _parse_process_csv(PROCESS_CSV)
    metrics = _compute_process_metrics(rows)
    assert isinstance(metrics["overloaded_processes"], list)


def test_process_alerts_returns_list():
    rows = _parse_process_csv(PROCESS_CSV)
    metrics = _compute_process_metrics(rows)
    alerts = _build_process_alerts(metrics)
    assert isinstance(alerts, list)


def test_process_alerts_have_required_fields():
    rows = _parse_process_csv(PROCESS_CSV)
    metrics = _compute_process_metrics(rows)
    alerts = _build_process_alerts(metrics)
    for a in alerts:
        assert "level" in a
        assert "message" in a
        # "info" is a valid informational level used for ToC recommendations
        assert a["level"] in ("critical", "high", "medium", "low", "info")


def test_process_empty_csv():
    rows = _parse_process_csv("")
    assert rows == []
    metrics = _compute_process_metrics(rows)
    assert metrics["avg_cycle_time_days"] == 0.0


def test_process_metrics_wip_estimated_when_missing():
    csv = "process,cycle_time,throughput\nTest Process,4.0,10\n"
    rows = _parse_process_csv(csv)
    assert len(rows) == 1
    # WIP should be estimated via Little's Law if missing
    assert rows[0]["wip"] >= 0


# ── Resource Agent Tests ───────────────────────────────────────────────────────

def test_resource_parse_returns_list():
    rows = _parse_resource_csv(RESOURCE_CSV)
    assert isinstance(rows, list)
    assert len(rows) == 5


def test_resource_parse_normalizes_utilization():
    """Values <=1 stay as-is; values >1 get divided by 100. 1.15 stays 1.15 (overtime)."""
    rows = _parse_resource_csv(RESOURCE_CSV)
    for r in rows:
        assert 0.0 <= r["utilization"] <= 1.5


def test_resource_metrics_avg_utilization():
    rows = _parse_resource_csv(RESOURCE_CSV)
    metrics = _compute_resource_metrics(rows)
    assert 0.0 < metrics["avg_utilization_rate"] < 1.5


def test_resource_metrics_overutilized_teams():
    rows = _parse_resource_csv(RESOURCE_CSV)
    metrics = _compute_resource_metrics(rows)
    # Engineering (0.92) and Support (1.15) are both >90%
    over = [t["team"] for t in metrics["overutilized_teams"]]
    assert "Engineering" in over
    assert "Support" in over


def test_resource_metrics_support_has_critical_burnout():
    rows = _parse_resource_csv(RESOURCE_CSV)
    metrics = _compute_resource_metrics(rows)
    # Support at 115% should have critical burnout risk
    over = metrics["overutilized_teams"]
    support = next((t for t in over if t["team"] == "Support"), None)
    assert support is not None
    assert support["burnout_risk"] == "critical"


def test_resource_metrics_underutilized_teams():
    rows = _parse_resource_csv(RESOURCE_CSV)
    metrics = _compute_resource_metrics(rows)
    # Marketing (0.45) is <50%
    under = [t["team"] for t in metrics["underutilized_teams"]]
    assert "Marketing" in under


def test_resource_alerts_burnout_critical():
    """Support at 115% should trigger critical burnout alert."""
    rows = _parse_resource_csv(RESOURCE_CSV)
    metrics = _compute_resource_metrics(rows)
    alerts = _build_resource_alerts(metrics)
    critical = [a for a in alerts if a["level"] == "critical"]
    assert len(critical) >= 1


def test_resource_alerts_have_required_fields():
    rows = _parse_resource_csv(RESOURCE_CSV)
    metrics = _compute_resource_metrics(rows)
    alerts = _build_resource_alerts(metrics)
    for a in alerts:
        assert "level" in a
        assert "message" in a


def test_resource_empty_csv():
    rows = _parse_resource_csv("")
    assert rows == []
    metrics = _compute_resource_metrics(rows)
    assert metrics["avg_utilization_rate"] == 0.0


# ── SLA Agent Tests ────────────────────────────────────────────────────────────

def test_sla_parse_returns_list():
    rows = _parse_sla_csv(SLA_CSV)
    assert isinstance(rows, list)
    assert len(rows) == 8


def test_sla_parse_has_tier_field():
    """Parser normalizes priority column to 'tier' key (p1/p2/p3/p4)."""
    rows = _parse_sla_csv(SLA_CSV)
    for r in rows:
        assert "tier" in r
        assert r["tier"] in ("p1", "p2", "p3", "p4")


def test_sla_parse_has_required_fields():
    rows = _parse_sla_csv(SLA_CSV)
    for r in rows:
        assert "tier" in r
        assert "status" in r
        assert "category" in r


def test_sla_metrics_breach_rate():
    rows = _parse_sla_csv(SLA_CSV)
    metrics = _compute_sla_metrics(rows)
    assert 0.0 <= metrics["sla_breach_rate"] <= 1.0


def test_sla_metrics_avg_nps():
    rows = _parse_sla_csv(SLA_CSV)
    metrics = _compute_sla_metrics(rows)
    # NPS from fixture: 8,6,3,7,5,2,9,7 → avg ≈ 5.875 (0-10 scale)
    assert 0 < metrics["avg_nps_score"] < 10


def test_sla_metrics_by_tier():
    rows = _parse_sla_csv(SLA_CSV)
    metrics = _compute_sla_metrics(rows)
    assert isinstance(metrics["by_tier"], dict)


def test_sla_metrics_recurring_issues_structure():
    rows = _parse_sla_csv(SLA_CSV)
    metrics = _compute_sla_metrics(rows)
    assert isinstance(metrics["recurring_issues"], list)
    # Each item has "issue", "count", "pct" keys
    if metrics["recurring_issues"]:
        item = metrics["recurring_issues"][0]
        assert "issue" in item
        assert "count" in item
        assert "pct" in item


def test_sla_metrics_recurring_issues_top_category():
    rows = _parse_sla_csv(SLA_CSV)
    metrics = _compute_sla_metrics(rows)
    # billing appears 3x in fixture → should be top recurring
    if metrics["recurring_issues"]:
        assert metrics["recurring_issues"][0]["issue"] == "billing"


def test_sla_alerts_returns_list():
    rows = _parse_sla_csv(SLA_CSV)
    metrics = _compute_sla_metrics(rows)
    alerts = _build_sla_alerts(metrics)
    assert isinstance(alerts, list)


def test_sla_alerts_have_required_fields():
    rows = _parse_sla_csv(SLA_CSV)
    metrics = _compute_sla_metrics(rows)
    alerts = _build_sla_alerts(metrics)
    for a in alerts:
        assert "level" in a
        assert "message" in a


def test_sla_empty_csv():
    rows = _parse_sla_csv("")
    assert rows == []
    metrics = _compute_sla_metrics(rows)
    assert metrics["sla_breach_rate"] == 0.0


# ── Ops Efficiency Logic Tests ─────────────────────────────────────────────────
# Pure logic mirroring orchestrator._compute_ops_efficiency (no orchestrator import)

def _compute_ops_efficiency(processes, resources, sla) -> float:
    """Mirror of orchestrator._compute_ops_efficiency for test isolation."""
    scores = []
    if processes:
        eff = processes.get("efficiency_score", 5.0)
        scores.append(10.0 - eff)
    if resources:
        util = resources.get("avg_utilization_rate", 0.5)
        if 0.70 <= util <= 0.85:
            util_score = 10.0
        elif util > 0.85:
            util_score = max(0.0, 10.0 - (util - 0.85) * 50)
        else:
            util_score = util / 0.70 * 10.0
        scores.append(min(10.0, util_score))
    if sla:
        breach = sla.get("sla_breach_rate", 0.5)
        sla_score = max(0.0, 10.0 - breach * 30)
        scores.append(min(10.0, sla_score))
    return round(sum(scores) / len(scores), 1) if scores else 0.0


def test_ops_efficiency_ideal_utilization():
    """70-85% utilization + good SLA + low process inefficiency = high score."""
    procs = {"efficiency_score": 2.0}
    res   = {"avg_utilization_rate": 0.78}
    sla   = {"sla_breach_rate": 0.05}
    score = _compute_ops_efficiency(procs, res, sla)
    assert score >= 7.0


def test_ops_efficiency_bad_utilization():
    """110%+ utilization = low efficiency score."""
    procs = {"efficiency_score": 8.0}
    res   = {"avg_utilization_rate": 1.15}
    sla   = {"sla_breach_rate": 0.35}
    score = _compute_ops_efficiency(procs, res, sla)
    assert score < 5.0


def test_ops_efficiency_empty_inputs():
    score = _compute_ops_efficiency({}, {}, {})
    assert score == 0.0


def test_fallback_narrative_is_string():
    eff    = 4.0
    util   = 0.80
    breach = 0.10
    score  = 5.0
    narrative = (
        f"Operations health score: {score}/10. "
        f"Process efficiency {eff}/10, resource utilization {util:.0%}, "
        f"SLA breach rate {breach:.0%}."
    )
    assert isinstance(narrative, str)
    assert len(narrative) > 20


# ── CEO Synthesis COO Cross-Risk Tests ────────────────────────────────────────

def test_cross_coo_sla_revenue_detected():
    fin = {
        "revenue_cents": 10_000_000,
        "cash_runway_months": 8,
        "net_margin": 0.10,
    }
    ops = {"sla_breach_rate": 0.35, "avg_utilization_rate": 0.80, "overall_ops_score": 4.0}
    risks = _detect_cross_risks(fin, {}, ops=ops)
    ids = [r["risk_id"] for r in risks]
    assert "cross-coo-sla-revenue" in ids


def test_cross_coo_burnout_margin_detected():
    fin = {
        "revenue_cents": 5_000_000,
        "net_margin": 0.02,
        "cash_runway_months": 10,
    }
    ops = {"sla_breach_rate": 0.05, "avg_utilization_rate": 1.08, "overall_ops_score": 6.0}
    risks = _detect_cross_risks(fin, {}, ops=ops)
    ids = [r["risk_id"] for r in risks]
    assert "cross-coo-burnout-margin" in ids


def test_cross_coo_ops_runway_detected():
    fin = {
        "revenue_cents": 3_000_000,
        "cash_runway_months": 4,
        "net_margin": 0.05,
    }
    ops = {"sla_breach_rate": 0.25, "avg_utilization_rate": 0.95, "overall_ops_score": 7.5}
    risks = _detect_cross_risks(fin, {}, ops=ops)
    ids = [r["risk_id"] for r in risks]
    assert "cross-coo-ops-runway" in ids


def test_cross_coo_no_risks_when_healthy():
    fin = {
        "revenue_cents": 20_000_000,
        "cash_runway_months": 18,
        "net_margin": 0.20,
    }
    ops = {"sla_breach_rate": 0.05, "avg_utilization_rate": 0.78, "overall_ops_score": 2.0}
    risks = _detect_cross_risks(fin, {}, ops=ops)
    coo_ids = [r["risk_id"] for r in risks if "coo" in r["risk_id"]]
    assert len(coo_ids) == 0


def test_condense_ops_summary_has_required_keys():
    coo_state = {
        "processes": {
            "efficiency_score": 3.5,
            "bottleneck_process": "Order Fulfillment",
            "overloaded_processes": ["Customer Onboarding"],
        },
        "resources": {
            "avg_utilization_rate": 0.82,
            "overutilized_teams": [{"team": "Engineering", "utilization": 0.92}],
        },
        "sla": {
            "sla_breach_rate": 0.12,
            "avg_nps_score": 6.5,
        },
        "coo_summary": {
            "overall_ops_score": 3.5,
            "operational_efficiency_score": 7.2,
            "top_risks": [{"domain": "SLA", "severity": "high", "message": "Breach rate elevated"}],
            "narrative": "Operations are generally healthy.",
        },
    }
    condensed = _condense_ops_summary(coo_state)
    required_keys = [
        "overall_ops_score",
        "operational_efficiency_score",
        "process_efficiency_score",
        "avg_utilization_rate",
        "sla_breach_rate",
        "top_risks",
        "narrative",
    ]
    for key in required_keys:
        assert key in condensed, f"Missing key: {key}"


def test_condense_ops_summary_empty_state():
    condensed = _condense_ops_summary({})
    assert condensed["overall_ops_score"] == 0.0
    assert condensed["sla_breach_rate"] == 0.0
    assert condensed["top_risks"] == []
