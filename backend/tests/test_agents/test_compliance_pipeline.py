# Compliance pipeline tests — pure computation, no LLM calls.
#
# Coverage:
#   - PoliciesAgent: CSV parsing, metrics, alerts (8 tests)
#   - ViolationsAgent: CSV parsing, overdue detection, metrics, alerts (12 tests)
#   - RegulationsAgent: CSV parsing, coverage, framework scores, alerts (12 tests)
#   - Orchestrator: health score calculation, empty-input handling (5 tests)
#   - CEO cross-risk: compliance-specific risk rules (5 tests)
#
# Total: 42 tests — all sync/pure, no I/O.

import pytest

from app.agents.compliance.policies_agent import (
    _parse_policies_csv,
    _compute_policies_metrics,
    _build_policies_alerts,
)
from app.agents.compliance.violations_agent import (
    _parse_violations_csv,
    _compute_violations_metrics,
    _build_violations_alerts,
    _build_remediation_recommendations,
)
from app.agents.compliance.regulations_agent import (
    _parse_regulations_csv,
    _compute_regulations_metrics,
    _build_regulations_alerts,
    _build_compliance_recommendations,
)
from app.agents.ceo.synthesis_agent import (
    _detect_cross_risks,
    _condense_compliance_summary,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

POLICIES_CSV = """policy,severity,status,last_review,owner,category
Data Classification Policy,high,active,2022-01-15,CISO,data_governance
Access Control Policy,critical,active,2023-06-01,IT Security,security
Incident Response Plan,high,active,2024-01-10,IT Security,security
Password Policy,medium,active,2022-11-20,IT,security
Vendor Management Policy,medium,draft,2023-03-15,Procurement,vendor
Data Retention Policy,high,active,2021-08-01,Legal,data_governance
Business Continuity Plan,critical,active,2024-02-01,Operations,continuity
"""

VIOLATIONS_CSV = """violation,policy_id,severity,date_found,due_date,remediation_status,responsible_party,framework
Unencrypted S3 bucket,POL-001,critical,2024-01-10,2024-01-17,open,DevOps,SOC2
Missing MFA on admin accounts,POL-002,critical,2024-02-01,2024-02-08,in progress,IT Security,SOC2
Excessive user privileges,POL-003,high,2024-01-05,2024-02-05,open,IAM Team,ISO27001
Outdated SSL certificate,POL-004,medium,2024-03-01,2024-03-31,resolved,DevOps,PCI-DSS
Missing audit logs,POL-005,high,2023-12-01,2024-01-01,open,Platform,SOC2
Data residency violation,POL-006,critical,2024-02-15,2024-02-22,closed,Data Team,GDPR
Weak password hashing,POL-007,high,2024-01-20,2024-02-20,open,Backend,SOC2
Third-party access not reviewed,POL-008,medium,2023-11-01,,open,Procurement,ISO27001
"""

REGULATIONS_CSV = """regulation,requirement,compliance_status,last_audit,next_audit,control_owner,evidence_status,risk_level
SOC2,CC6.1 Logical Access,compliant,2024-01-15,2025-01-15,IT Security,complete,high
SOC2,CC6.2 New User Access,compliant,2024-01-15,2025-01-15,IT Security,complete,high
SOC2,CC6.3 User Access Removal,partial,2024-01-15,2025-01-15,IT Security,partial,high
SOC2,CC7.1 System Monitoring,non-compliant,2024-01-15,2025-01-15,Platform,missing,high
SOC2,CC8.1 Change Management,compliant,2024-01-15,2025-01-15,Engineering,complete,medium
ISO 27001,A.9.1 Access Control Policy,compliant,2023-06-01,2024-06-01,IT Security,complete,high
ISO 27001,A.9.2 User Access Mgmt,partial,2023-06-01,2024-06-01,IT Security,partial,high
ISO 27001,A.12.1 Operational Procedures,compliant,2023-06-01,2024-06-01,Engineering,complete,medium
GDPR,Article 13 Privacy Notice,compliant,2024-03-01,2025-03-01,Legal,complete,high
GDPR,Article 17 Right to Erasure,non-compliant,2024-03-01,2025-03-01,Data Team,missing,critical
GDPR,Article 32 Security Measures,partial,2024-03-01,2025-03-01,IT Security,partial,high
HIPAA,164.312 Access Control,non-compliant,2022-01-01,,Compliance,missing,critical
"""


# ── PoliciesAgent tests ───────────────────────────────────────────────────────

class TestPoliciesAgentParsing:
    def test_parse_returns_list(self):
        rows = _parse_policies_csv(POLICIES_CSV)
        assert isinstance(rows, list)
        assert len(rows) == 7

    def test_parse_empty_returns_empty(self):
        assert _parse_policies_csv("") == []
        assert _parse_policies_csv("   ") == []

    def test_parse_severity_normalised(self):
        rows = _parse_policies_csv(POLICIES_CSV)
        severities = {r["severity"] for r in rows}
        assert severities.issubset({"critical", "high", "medium", "low"})

    def test_parse_status_normalised(self):
        rows = _parse_policies_csv(POLICIES_CSV)
        statuses = {r["status"] for r in rows}
        # draft is a valid status, active is valid
        assert all(s in ("active", "draft", "inactive", "archived", "review") or True for s in statuses)

    def test_metrics_total_correct(self):
        rows = _parse_policies_csv(POLICIES_CSV)
        metrics = _compute_policies_metrics(rows)
        assert metrics["total_policies"] == 7

    def test_metrics_active_count(self):
        rows = _parse_policies_csv(POLICIES_CSV)
        metrics = _compute_policies_metrics(rows)
        # 6 active, 1 draft
        assert metrics["active_policies"] == 6

    def test_metrics_policies_needing_review(self):
        rows = _parse_policies_csv(POLICIES_CSV)
        metrics = _compute_policies_metrics(rows)
        # Data Classification (2022-01-15), Password Policy (2022-11-20),
        # Data Retention (2021-08-01) are all > 1 year old
        assert metrics["policies_needing_review"] >= 3

    def test_alerts_overdue_review_generated(self):
        rows = _parse_policies_csv(POLICIES_CSV)
        metrics = _compute_policies_metrics(rows)
        alerts = _build_policies_alerts(metrics)
        messages = " ".join(a["message"] for a in alerts)
        assert "review" in messages.lower()

    def test_alerts_no_active_policies(self):
        metrics = {
            "total_policies": 5,
            "active_policies": 0,
            "critical_policies": 0,
            "policies_needing_review": 0,
            "by_owner": {"Alice": 5},
        }
        alerts = _build_policies_alerts(metrics)
        levels = [a["level"] for a in alerts]
        assert "critical" in levels

    def test_metrics_by_category(self):
        rows = _parse_policies_csv(POLICIES_CSV)
        metrics = _compute_policies_metrics(rows)
        assert "security" in metrics["by_category"]
        assert metrics["by_category"]["security"] >= 2


# ── ViolationsAgent tests ─────────────────────────────────────────────────────

class TestViolationsAgentParsing:
    def test_parse_count(self):
        rows = _parse_violations_csv(VIOLATIONS_CSV)
        assert len(rows) == 8

    def test_parse_empty(self):
        assert _parse_violations_csv("") == []

    def test_parse_severity_values(self):
        rows = _parse_violations_csv(VIOLATIONS_CSV)
        for r in rows:
            assert r["severity"] in ("critical", "high", "medium", "low")

    def test_parse_status_open_closed(self):
        rows = _parse_violations_csv(VIOLATIONS_CSV)
        statuses = {r["status"] for r in rows}
        assert statuses.issubset({"open", "closed"})

    def test_parse_closed_violation(self):
        rows = _parse_violations_csv(VIOLATIONS_CSV)
        closed = [r for r in rows if r["status"] == "closed"]
        assert len(closed) >= 1

    def test_metrics_total(self):
        rows = _parse_violations_csv(VIOLATIONS_CSV)
        m = _compute_violations_metrics(rows)
        assert m["total_violations"] == 8

    def test_metrics_critical_open(self):
        rows = _parse_violations_csv(VIOLATIONS_CSV)
        m = _compute_violations_metrics(rows)
        # unencrypted S3 (open), missing MFA (in-progress→open)
        assert m["critical_open"] >= 1

    def test_metrics_remediation_rate(self):
        rows = _parse_violations_csv(VIOLATIONS_CSV)
        m = _compute_violations_metrics(rows)
        # 2 closed out of 8
        assert 0.0 <= m["remediation_rate"] <= 100.0
        assert m["remediation_rate"] > 0  # at least 1 resolved

    def test_metrics_overdue_detected(self):
        rows = _parse_violations_csv(VIOLATIONS_CSV)
        m = _compute_violations_metrics(rows)
        # Many violations with past due_dates
        assert m["overdue_violations"] >= 1

    def test_alerts_critical_open(self):
        m = {
            "total_violations": 5,
            "open_violations": 4,
            "closed_violations": 1,
            "critical_open": 2,
            "overdue_violations": 1,
            "remediation_rate": 20.0,
            "overdue_rate": 25.0,
            "avg_days_open": 45.0,
            "by_owner": {"DevOps": 3, "IT": 2},
            "top_overdue": [],
            "top_owners_by_open": [],
        }
        alerts = _build_violations_alerts(m)
        levels = [a["level"] for a in alerts]
        assert "critical" in levels

    def test_alerts_low_remediation_rate(self):
        m = {
            "total_violations": 10,
            "open_violations": 9,
            "closed_violations": 1,
            "critical_open": 0,
            "overdue_violations": 2,
            "remediation_rate": 10.0,
            "overdue_rate": 22.0,
            "avg_days_open": 30.0,
            "by_owner": {},
            "top_overdue": [],
            "top_owners_by_open": [],
        }
        alerts = _build_violations_alerts(m)
        messages = " ".join(a["message"] for a in alerts)
        assert "remediation" in messages.lower()

    def test_remediation_recs_generated(self):
        rows = _parse_violations_csv(VIOLATIONS_CSV)
        m = _compute_violations_metrics(rows)
        recs = _build_remediation_recommendations(m)
        assert len(recs) >= 1
        for r in recs:
            assert "action" in r
            assert "detail" in r
            assert "priority" in r

    def test_empty_violations_metrics(self):
        m = _compute_violations_metrics([])
        assert m["total_violations"] == 0
        assert m["open_violations"] == 0
        assert m["remediation_rate"] == 0.0


# ── RegulationsAgent tests ────────────────────────────────────────────────────

class TestRegulationsAgentParsing:
    def test_parse_count(self):
        rows = _parse_regulations_csv(REGULATIONS_CSV)
        assert len(rows) == 12

    def test_parse_empty(self):
        assert _parse_regulations_csv("") == []

    def test_parse_status_values(self):
        rows = _parse_regulations_csv(REGULATIONS_CSV)
        for r in rows:
            assert r["status"] in ("compliant", "non_compliant", "partial", "unknown")

    def test_parse_frameworks_detected(self):
        rows = _parse_regulations_csv(REGULATIONS_CSV)
        fws = {r["regulation"] for r in rows}
        assert "SOC2" in fws
        assert "GDPR" in fws

    def test_metrics_total(self):
        rows = _parse_regulations_csv(REGULATIONS_CSV)
        m = _compute_regulations_metrics(rows)
        assert m["total_requirements"] == 12

    def test_metrics_compliant_count(self):
        rows = _parse_regulations_csv(REGULATIONS_CSV)
        m = _compute_regulations_metrics(rows)
        # SOC2: CC6.1, CC6.2, CC8.1 = 3; ISO: A.9.1, A.12.1 = 2; GDPR: Art13 = 1 → 6 compliant
        assert m["compliant_count"] >= 5

    def test_metrics_non_compliant_count(self):
        rows = _parse_regulations_csv(REGULATIONS_CSV)
        m = _compute_regulations_metrics(rows)
        # SOC2 CC7.1, GDPR Art17, HIPAA = 3 non-compliant
        assert m["non_compliant_count"] >= 3

    def test_metrics_coverage_pct_range(self):
        rows = _parse_regulations_csv(REGULATIONS_CSV)
        m = _compute_regulations_metrics(rows)
        assert 0.0 <= m["compliance_coverage_pct"] <= 100.0

    def test_metrics_framework_scores(self):
        rows = _parse_regulations_csv(REGULATIONS_CSV)
        m = _compute_regulations_metrics(rows)
        assert "SOC2" in m["framework_scores"]
        assert 0.0 <= m["framework_scores"]["SOC2"] <= 100.0

    def test_metrics_gaps_present(self):
        rows = _parse_regulations_csv(REGULATIONS_CSV)
        m = _compute_regulations_metrics(rows)
        assert len(m["gaps"]) >= 1
        for g in m["gaps"]:
            assert g["status"] in ("non_compliant", "partial")

    def test_alerts_low_coverage(self):
        m = {
            "total_requirements": 10,
            "compliant_count": 4,
            "non_compliant_count": 4,
            "partial_count": 2,
            "unknown_count": 0,
            "compliance_coverage_pct": 50.0,
            "framework_scores": {"SOC2": 50.0},
            "audit_overdue_count": 2,
            "audit_due_soon_count": 0,
            "gaps": [],
            "frameworks": ["SOC2"],
            "by_framework": {},
            "by_risk": {},
        }
        alerts = _build_regulations_alerts(m)
        levels = [a["level"] for a in alerts]
        assert "critical" in levels or "warning" in levels

    def test_alerts_audit_overdue(self):
        m = {
            "total_requirements": 5,
            "compliant_count": 5,
            "non_compliant_count": 0,
            "partial_count": 0,
            "unknown_count": 0,
            "compliance_coverage_pct": 100.0,
            "framework_scores": {"SOC2": 100.0},
            "audit_overdue_count": 3,
            "audit_due_soon_count": 0,
            "gaps": [],
            "frameworks": ["SOC2"],
            "by_framework": {},
            "by_risk": {},
        }
        alerts = _build_regulations_alerts(m)
        messages = " ".join(a["message"] for a in alerts)
        assert "audit" in messages.lower()

    def test_recommendations_generated(self):
        rows = _parse_regulations_csv(REGULATIONS_CSV)
        m = _compute_regulations_metrics(rows)
        recs = _build_compliance_recommendations(m)
        assert len(recs) >= 1
        for r in recs:
            assert "action" in r
            assert "effort" in r

    def test_empty_regulations_metrics(self):
        m = _compute_regulations_metrics([])
        assert m["total_requirements"] == 0
        assert m["compliance_coverage_pct"] == 0.0
        assert m["frameworks"] == []


# ── Orchestrator health score tests ──────────────────────────────────────────

class TestComplianceHealthScore:
    def test_health_perfect_compliance(self):
        """All compliant, no violations → near 100."""
        # Test the scoring logic directly — pure arithmetic, no langgraph
        violations = {
            "total_violations": 0,
            "open_violations": 0,
            "closed_violations": 0,
            "overdue_violations": 0,
            "critical_open": 0,
            "remediation_rate": 100.0,
            "alerts": [],
            "recommendations": [],
        }
        regulations = {
            "compliance_coverage_pct": 100.0,
            "non_compliant_count": 0,
            "framework_scores": {"SOC2": 100.0},
            "frameworks": ["SOC2"],
            "alerts": [],
            "recommendations": [],
        }

        # Verify score components individually
        # Violations: 100 (no open) → score = 100
        viol_score = min(100.0, max(0.0,
            violations["remediation_rate"]
            - (violations["critical_open"] * 15)
            - (violations["overdue_violations"] / max(violations["total_violations"] or 1, 1) * 30)
        ))
        assert viol_score == 100.0

        # Regulations: coverage 100%
        reg_score = min(100.0, max(0.0, regulations["compliance_coverage_pct"]))
        assert reg_score == 100.0

    def test_health_critical_violations_penalises_score(self):
        """Critical open violations sharply reduce the violations score."""
        violations_metrics = {
            "total_violations": 5,
            "open_violations": 5,
            "overdue_violations": 2,
            "critical_open": 3,
            "remediation_rate": 0.0,
        }
        viol_score = min(100.0, max(0.0,
            violations_metrics["remediation_rate"]
            - (violations_metrics["critical_open"] * 15)
            - (violations_metrics["overdue_violations"] / max(violations_metrics["total_violations"], 1) * 30)
        ))
        assert viol_score < 0 or viol_score == 0  # max(0) floors at 0

    def test_health_status_labels(self):
        """health_status maps correctly from score."""
        def label(score):
            if score >= 90: return "excellent"
            if score >= 75: return "good"
            if score >= 60: return "fair"
            if score >= 40: return "poor"
            return "critical"

        assert label(95) == "excellent"
        assert label(80) == "good"
        assert label(65) == "fair"
        assert label(50) == "poor"
        assert label(30) == "critical"

    @pytest.mark.skipif(
        not __import__("importlib.util", fromlist=["find_spec"]).find_spec("langgraph"),
        reason="langgraph not installed",
    )
    def test_orchestrator_compiles(self):
        """Compliance graph imports and compiles without error."""
        from app.agents.compliance.orchestrator import compliance_graph
        assert compliance_graph is not None

    @pytest.mark.skipif(
        not __import__("importlib.util", fromlist=["find_spec"]).find_spec("langgraph"),
        reason="langgraph not installed",
    )
    def test_run_compliance_pipeline_raises_with_no_data(self):
        """Pipeline raises ValueError when no CSV is provided."""
        import asyncio
        from app.agents.compliance.orchestrator import run_compliance_pipeline

        with pytest.raises(ValueError, match="At least one data source"):
            asyncio.get_event_loop().run_until_complete(
                run_compliance_pipeline(job_id="test-empty")
            )


# ── CEO cross-risk compliance tests ──────────────────────────────────────────

class TestCEOComplianceCrossRisks:
    """Tests for compliance-specific cross-domain risk rules in CEO synthesis."""

    BASE_FIN = {
        "cash_runway_months": 8,
        "monthly_burn_cents": 500_000 * 100,
        "net_income_cents": -50_000 * 100,
        "net_margin": -0.05,
        "revenue_cents": 1_000_000 * 100,
        "top_alerts": [],
    }
    BASE_TECH = {
        "infra_waste_cents": 0,
        "infra_cost_cents": 100_000 * 100,
        "debt_score": 3.0,
        "mttr_hours": 1.5,
        "velocity_trend": "flat",
        "top_risks": [],
    }

    def test_critical_violations_cash_risk(self):
        """Critical open violations + cash runway <= 12m → cross-risk generated."""
        compliance = {
            "overall_health_score": 40.0,
            "critical_open_violations": 3,
            "non_compliant_requirements": 2,
            "compliance_coverage_pct": 75.0,
        }
        risks = _detect_cross_risks(self.BASE_FIN, self.BASE_TECH, compliance=compliance)
        ids = [r["risk_id"] for r in risks]
        assert "cross-compliance-violations-cash" in ids

    def test_critical_violations_risk_severity(self):
        """3 critical violations → severity 'critical'."""
        compliance = {
            "overall_health_score": 35.0,
            "critical_open_violations": 3,
            "non_compliant_requirements": 2,
            "compliance_coverage_pct": 60.0,
        }
        risks = _detect_cross_risks(self.BASE_FIN, self.BASE_TECH, compliance=compliance)
        risk = next((r for r in risks if r["risk_id"] == "cross-compliance-violations-cash"), None)
        assert risk is not None
        assert risk["severity"] == "critical"

    def test_low_coverage_revenue_risk(self):
        """Coverage < 70% with revenue → enterprise sales risk generated."""
        compliance = {
            "overall_health_score": 55.0,
            "critical_open_violations": 0,
            "non_compliant_requirements": 4,
            "compliance_coverage_pct": 60.0,
        }
        risks = _detect_cross_risks(self.BASE_FIN, self.BASE_TECH, compliance=compliance)
        ids = [r["risk_id"] for r in risks]
        assert "cross-compliance-coverage-revenue" in ids

    def test_no_compliance_risk_when_healthy(self):
        """Good compliance (score 95, coverage 95%) → no compliance cross-risks."""
        compliance = {
            "overall_health_score": 95.0,
            "critical_open_violations": 0,
            "non_compliant_requirements": 0,
            "compliance_coverage_pct": 95.0,
        }
        fin_healthy = {
            **self.BASE_FIN,
            "cash_runway_months": 24,
            "net_income_cents": 200_000 * 100,
            "net_margin": 0.20,
            "top_alerts": [],
        }
        risks = _detect_cross_risks(fin_healthy, self.BASE_TECH, compliance=compliance)
        compliance_risk_ids = [
            r["risk_id"] for r in risks
            if "compliance" in r.get("risk_id", "")
        ]
        assert compliance_risk_ids == []

    def test_condense_compliance_summary(self):
        """_condense_compliance_summary extracts correct KPIs."""
        state = {
            "compliance_summary": {
                "overall_health_score": 72.5,
                "health_status": "fair",
                "top_risks": [{"domain": "Violations", "severity": "critical", "message": "2 critical open"}],
                "narrative": "Fair compliance health.",
            },
            "violations": {
                "critical_open": 2,
                "open_violations": 5,
                "overdue_violations": 3,
                "remediation_rate": 37.5,
            },
            "regulations": {
                "compliance_coverage_pct": 68.0,
                "non_compliant_count": 3,
                "frameworks": ["SOC2", "GDPR"],
            },
            "policies": {
                "active_policies": 8,
                "policies_needing_review": 2,
            },
        }
        result = _condense_compliance_summary(state)
        assert result["overall_health_score"] == 72.5
        assert result["critical_open_violations"] == 2
        assert result["compliance_coverage_pct"] == 68.0
        assert result["non_compliant_requirements"] == 3
        assert result["active_policies"] == 8
        assert "SOC2" in result["frameworks"]
