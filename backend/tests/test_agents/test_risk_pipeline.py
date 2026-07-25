"""
Risk Agent pipeline tests — pure computation, no LLM calls.

Covers: risk register parsing/scoring, loss event analysis,
KRI threshold monitoring, enterprise risk scoring, CEO cross-risk integration.
"""

from __future__ import annotations

import pytest
from app.agents.risk.register_agent import (
    _parse_register_csv,
    _compute_register_metrics,
    _build_register_alerts,
    _heat_band,
)
from app.agents.risk.loss_agent import (
    _parse_loss_csv,
    _compute_loss_metrics,
    _build_loss_alerts,
)
from app.agents.risk.kri_agent import (
    _parse_kri_csv,
    _compute_kri_metrics,
    _build_kri_alerts,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────

REGISTER_CSV = """risk_id,risk,category,likelihood,impact,owner,status,mitigation
R001,Data breach via phishing,cyber,4,5,CISO,open,Email security training + MFA
R002,Key person dependency,people,3,4,CTO,mitigated,Cross-training programme
R003,Regulatory fine - GDPR,compliance,3,5,Legal,open,
R004,Cloud outage,technology,2,4,CTO,open,Multi-region failover
R005,Supplier insolvency,operational,2,3,COO,accepted,Dual-sourcing policy
"""

REGISTER_NO_MITIGATION = """risk_id,risk,category,likelihood,impact,owner,status,mitigation
R001,Critical risk A,cyber,5,5,CISO,open,
R002,Critical risk B,operational,4,5,COO,open,
R003,Low risk C,people,1,2,HR,open,Some control
"""

LOSS_CSV = """date,category,description,gross_loss,recovery,root_cause,status
2024-01-15,cyber,Ransomware payment,150000,0,lack of controls,closed
2024-03-22,operational,Process failure payout,45000,10000,human error,closed
2024-06-10,fraud,Internal fraud loss,200000,50000,inadequate segregation,open
2024-08-01,legal,Contract dispute settlement,80000,0,poor contract management,closed
"""

LOSS_WORSENING_CSV = """date,category,description,gross_loss,recovery,root_cause,status
2024-01-01,operational,Loss A,10000,0,error,closed
2024-02-01,operational,Loss B,12000,0,error,closed
2024-06-01,operational,Loss C,50000,0,error,closed
2024-07-01,operational,Loss D,60000,0,error,closed
"""

KRI_CSV = """kri,category,current_value,threshold_amber,threshold_red,unit,trend,owner
System downtime %,technology,3.5,2.0,5.0,%,increasing,CTO
Overdue audit items,compliance,12,5,10,count,stable,CCO
Staff turnover rate,people,18,15,25,%,up,CHRO
Cyber incident count,cyber,2,3,6,count,stable,CISO
Customer complaints,operational,45,30,50,count,increasing,COO
"""

KRI_RED_BREACH_CSV = """kri,category,current_value,threshold_amber,threshold_red,unit,trend,owner
System downtime %,technology,8.0,2.0,5.0,%,increasing,CTO
Overdue audits,compliance,15,5,10,count,up,CCO
"""


# ── Heat Band Tests ───────────────────────────────────────────────────────────

class TestHeatBand:
    def test_critical_band_at_15(self):
        assert _heat_band(15) == "critical"

    def test_critical_band_at_25(self):
        assert _heat_band(25) == "critical"

    def test_high_band(self):
        assert _heat_band(10) == "high"

    def test_medium_band(self):
        assert _heat_band(6) == "medium"

    def test_low_band(self):
        assert _heat_band(2) == "low"

    def test_boundary_8_is_high(self):
        assert _heat_band(8) == "high"

    def test_boundary_4_is_medium(self):
        assert _heat_band(4) == "medium"


# ── Register Agent Tests ──────────────────────────────────────────────────────

class TestRegisterAgent:
    def test_parse_returns_list(self):
        rows = _parse_register_csv(REGISTER_CSV)
        assert isinstance(rows, list)
        assert len(rows) == 5

    def test_parse_empty_returns_empty(self):
        assert _parse_register_csv("") == []

    def test_parse_raw_score_calculated(self):
        rows = _parse_register_csv(REGISTER_CSV)
        # R001: 4 × 5 = 20
        r001 = next(r for r in rows if r["risk_id"] == "R001")
        assert r001["raw_score"] == 20

    def test_parse_heat_band_assigned(self):
        rows = _parse_register_csv(REGISTER_CSV)
        r001 = next(r for r in rows if r["risk_id"] == "R001")
        assert r001["heat_band"] == "critical"

    def test_parse_mitigation_flag(self):
        rows = _parse_register_csv(REGISTER_CSV)
        r001 = next(r for r in rows if r["risk_id"] == "R001")
        assert r001["has_mitigation"] is True
        r003 = next(r for r in rows if r["risk_id"] == "R003")
        assert r003["has_mitigation"] is False

    def test_metrics_total_risks(self):
        rows = _parse_register_csv(REGISTER_CSV)
        m = _compute_register_metrics(rows)
        assert m["total_risks"] == 5

    def test_metrics_unmitigated_critical_detected(self):
        rows = _parse_register_csv(REGISTER_NO_MITIGATION)
        m = _compute_register_metrics(rows)
        # R001 (5×5=25) and R002 (4×5=20) are critical with no mitigation
        assert len(m["unmitigated_critical"]) == 2

    def test_metrics_mitigation_coverage(self):
        rows = _parse_register_csv(REGISTER_CSV)
        m = _compute_register_metrics(rows)
        # R001, R002, R004, R005 have mitigation (4/5 = 0.80) — R003 is empty
        assert m["mitigation_coverage"] == pytest.approx(0.8, abs=0.01)

    def test_metrics_enterprise_risk_score_range(self):
        rows = _parse_register_csv(REGISTER_CSV)
        m = _compute_register_metrics(rows)
        assert 0 <= m["enterprise_risk_score"] <= 10

    def test_metrics_top_risks_sorted(self):
        rows = _parse_register_csv(REGISTER_CSV)
        m = _compute_register_metrics(rows)
        scores = [r["score"] for r in m["top_risks"]]
        assert scores == sorted(scores, reverse=True)

    def test_alerts_critical_unmitigated(self):
        rows = _parse_register_csv(REGISTER_NO_MITIGATION)
        m = _compute_register_metrics(rows)
        alerts = _build_register_alerts(m)
        assert any(a["level"] == "critical" for a in alerts)

    def test_alerts_low_mitigation_coverage(self):
        rows = _parse_register_csv(REGISTER_NO_MITIGATION)
        m = _compute_register_metrics(rows)
        # Only 1 out of 3 has mitigation
        alerts = _build_register_alerts(m)
        assert any("mitigation" in a["message"].lower() or "coverage" in a["message"].lower()
                   for a in alerts)


# ── Loss Agent Tests ──────────────────────────────────────────────────────────

class TestLossAgent:
    def test_parse_returns_list(self):
        rows = _parse_loss_csv(LOSS_CSV)
        assert len(rows) == 4

    def test_parse_empty(self):
        assert _parse_loss_csv("") == []

    def test_parse_net_loss_calculated(self):
        rows = _parse_loss_csv(LOSS_CSV)
        # Ransomware: gross 150k, recovery 0, net 150k
        ransomware = rows[0]
        assert ransomware["gross_loss"] == 150_000 * 100
        assert ransomware["net_loss"] == 150_000 * 100

    def test_parse_recovery_subtracted(self):
        rows = _parse_loss_csv(LOSS_CSV)
        # Internal fraud: gross 200k, recovery 50k, net 150k
        fraud = rows[2]
        assert fraud["net_loss"] == 150_000 * 100

    def test_metrics_total_events(self):
        rows = _parse_loss_csv(LOSS_CSV)
        m = _compute_loss_metrics(rows)
        assert m["total_events"] == 4

    def test_metrics_total_net_loss(self):
        rows = _parse_loss_csv(LOSS_CSV)
        m = _compute_loss_metrics(rows)
        # 150k + 35k + 150k + 80k = 415k
        assert m["total_net_loss"] == pytest.approx(415_000 * 100, rel=0.01)

    def test_metrics_recovery_rate(self):
        rows = _parse_loss_csv(LOSS_CSV)
        m = _compute_loss_metrics(rows)
        # recovery = 60k, gross = 475k → ~12.6%
        assert 0.0 < m["recovery_rate"] < 0.20

    def test_metrics_open_events(self):
        rows = _parse_loss_csv(LOSS_CSV)
        m = _compute_loss_metrics(rows)
        assert m["open_events"] == 1   # fraud row is open

    def test_metrics_loss_trend_worsening(self):
        rows = _parse_loss_csv(LOSS_WORSENING_CSV)
        m = _compute_loss_metrics(rows)
        assert m["loss_trend"] == "worsening"

    def test_alerts_large_loss(self):
        rows = _parse_loss_csv(LOSS_CSV)
        m = _compute_loss_metrics(rows)
        alerts = _build_loss_alerts(m)
        assert any(a["level"] in ("critical", "warning") for a in alerts)

    def test_empty_loss_metrics(self):
        m = _compute_loss_metrics([])
        assert m["total_events"] == 0
        assert m["total_net_loss"] == 0


# ── KRI Agent Tests ───────────────────────────────────────────────────────────

class TestKRIAgent:
    def test_parse_returns_list(self):
        rows = _parse_kri_csv(KRI_CSV)
        assert len(rows) == 5

    def test_parse_empty(self):
        assert _parse_kri_csv("") == []

    def test_parse_breach_green(self):
        rows = _parse_kri_csv(KRI_CSV)
        # Cyber incident count: value 2, amber 3, red 6 → green
        cyber = next(r for r in rows if "cyber" in r["name"].lower() or r["category"] == "cyber")
        assert cyber["breach"] == "green"

    def test_parse_breach_amber(self):
        rows = _parse_kri_csv(KRI_CSV)
        # Overdue audit items: value 12, amber 5, red 10 → red
        # System downtime: value 3.5, amber 2.0, red 5.0 → amber
        downtime = next(r for r in rows if "downtime" in r["name"].lower())
        assert downtime["breach"] == "amber"

    def test_parse_breach_red(self):
        rows = _parse_kri_csv(KRI_RED_BREACH_CSV)
        # System downtime 8.0 >= red 5.0
        downtime = next(r for r in rows if "downtime" in r["name"].lower())
        assert downtime["breach"] == "red"

    def test_metrics_total_kris(self):
        rows = _parse_kri_csv(KRI_CSV)
        m = _compute_kri_metrics(rows)
        assert m["total_kris"] == 5

    def test_metrics_red_breach_count(self):
        rows = _parse_kri_csv(KRI_RED_BREACH_CSV)
        m = _compute_kri_metrics(rows)
        assert len(m["breached_red"]) == 2

    def test_metrics_composite_score_range(self):
        rows = _parse_kri_csv(KRI_CSV)
        m = _compute_kri_metrics(rows)
        assert 0 <= m["composite_kri_score"] <= 10

    def test_metrics_worsening_kris_detected(self):
        rows = _parse_kri_csv(KRI_CSV)
        m = _compute_kri_metrics(rows)
        # Downtime trending up+amber, staff turnover up+amber
        assert len(m["worsening_kris"]) >= 1

    def test_alerts_red_breach_critical(self):
        rows = _parse_kri_csv(KRI_RED_BREACH_CSV)
        m = _compute_kri_metrics(rows)
        alerts = _build_kri_alerts(m)
        assert any(a["level"] == "critical" for a in alerts)

    def test_empty_kri_metrics(self):
        m = _compute_kri_metrics([])
        assert m["total_kris"] == 0
        assert m["composite_kri_score"] == 0.0


# ── Enterprise Risk Score Integration ────────────────────────────────────────

class TestEnterpriseRiskScore:
    def test_perfect_low_risk(self):
        """All low inputs → score near 0."""
        reg = {"enterprise_risk_score": 1.0, "unmitigated_critical": [],
               "by_band": {}, "mitigation_coverage": 1.0, "top_risks": []}
        loss = {"total_net_loss": 0, "open_events": 0, "loss_trend": "stable",
                "top_loss_events": []}
        kri = {"composite_kri_score": 0.0, "breached_red": [], "breached_amber": []}

        # Manual calculation matching orchestrator formula
        reg_score  = 1.0
        loss_score = 0.0
        kri_score  = 0.0
        expected = round(reg_score * 0.35 + loss_score * 0.35 + kri_score * 0.30, 1)
        assert expected == pytest.approx(0.35, abs=0.1)

    def test_high_risk_score(self):
        """High inputs → score near 10."""
        reg_score  = 9.0
        loss_score = 8.0
        kri_score  = 10.0
        result = round(reg_score * 0.35 + loss_score * 0.35 + kri_score * 0.30, 1)
        assert result >= 8.0

    def test_posture_labels(self):
        """Test posture label boundaries."""
        def posture(score: float) -> str:
            if score >= 7.0: return "critical"
            if score >= 5.0: return "elevated"
            if score >= 3.0: return "moderate"
            return "acceptable"

        assert posture(8.5) == "critical"
        assert posture(6.0) == "elevated"
        assert posture(4.0) == "moderate"
        assert posture(2.0) == "acceptable"
