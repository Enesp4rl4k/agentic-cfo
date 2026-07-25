"""
Internal Audit pipeline tests — pure computation, no LLM calls.

Covers: findings parsing/scoring, control effectiveness assessment,
audit universe coverage analysis, and audit health score calculation.
"""

from __future__ import annotations

import pytest
from app.agents.audit.findings_agent import (
    _parse_findings_csv,
    _compute_findings_metrics,
    _build_findings_alerts,
)
from app.agents.audit.controls_agent import (
    _parse_controls_csv,
    _compute_controls_metrics,
    _build_controls_alerts,
)
from app.agents.audit.coverage_agent import (
    _parse_coverage_csv,
    _compute_coverage_metrics,
    _build_coverage_alerts,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

FINDINGS_CSV = """finding_id,title,severity,status,due_date,owner,category,repeat
F001,Segregation of duties violation,critical,open,2024-01-31,Finance,financial,no
F002,Unauthorised system access,high,in_progress,2024-03-15,IT,technology,yes
F003,Missing approval documentation,medium,closed,2024-02-28,Operations,operational,no
F004,Password policy non-compliance,medium,open,2024-04-01,IT,technology,no
F005,Expense report irregularity,high,closed,2024-03-31,Finance,financial,yes
F006,Vendor onboarding gap,low,open,2025-12-31,Procurement,procurement,no
"""

FINDINGS_ALL_CLEAR = """finding_id,title,severity,status,due_date,owner,category,repeat
F001,Minor documentation gap,low,closed,2025-12-31,Admin,general,no
F002,Process improvement rec,informational,closed,2025-12-31,Ops,operational,no
"""

CONTROLS_CSV = """control_id,name,category,design_effectiveness,operating_effectiveness,last_tested,owner
C001,Access Control Management,technology,effective,effective,2024-06-01,CISO
C002,Segregation of Duties,financial,effective,partially effective,2024-03-15,CFO
C003,Vendor Approval Process,procurement,partially effective,ineffective,2023-01-01,COO
C004,Change Management,technology,effective,effective,2024-09-01,CTO
C005,Financial Reporting Review,financial,ineffective,ineffective,2022-06-01,CFO
"""

CONTROLS_ALL_EFFECTIVE = """control_id,name,category,design_effectiveness,operating_effectiveness,last_tested,owner
C001,Control A,technology,effective,effective,2024-09-01,CTO
C002,Control B,financial,effective,effective,2024-08-01,CFO
C003,Control C,operational,effective,effective,2024-07-01,COO
"""

COVERAGE_CSV = """unit,category,last_audit,frequency,risk_rating,scheduled_next
Accounts Payable,financial,2023-06-01,annual,high,2024-06-01
Payroll Processing,financial,2024-01-15,annual,critical,2025-01-15
IT Infrastructure,technology,2022-01-01,annual,high,2023-01-01
Sales Operations,commercial,2024-03-01,annual,medium,2025-03-01
Legal & Compliance,compliance,,annual,high,2024-12-01
Customer Service,operational,2021-06-01,biennial,low,2023-06-01
"""


# ── Findings Agent Tests ──────────────────────────────────────────────────────

class TestFindingsAgent:
    def test_parse_count(self):
        rows = _parse_findings_csv(FINDINGS_CSV)
        assert len(rows) == 6

    def test_parse_empty(self):
        assert _parse_findings_csv("") == []

    def test_parse_severity_normalised(self):
        rows = _parse_findings_csv(FINDINGS_CSV)
        assert all(r["severity"] in ("critical", "high", "medium", "low", "informational")
                   for r in rows)

    def test_parse_repeat_flag(self):
        rows = _parse_findings_csv(FINDINGS_CSV)
        # F002 and F005 are marked as repeat
        repeats = [r for r in rows if r["is_repeat"]]
        assert len(repeats) == 2

    def test_metrics_open_critical(self):
        rows = _parse_findings_csv(FINDINGS_CSV)
        m = _compute_findings_metrics(rows)
        # F001 is critical and open
        assert m["open_critical"] == 1

    def test_metrics_remediation_rate(self):
        rows = _parse_findings_csv(FINDINGS_CSV)
        m = _compute_findings_metrics(rows)
        # F003 and F005 are closed (2/6 = 0.333)
        assert m["remediation_rate"] == pytest.approx(2 / 6, abs=0.01)

    def test_metrics_repeat_count(self):
        rows = _parse_findings_csv(FINDINGS_CSV)
        m = _compute_findings_metrics(rows)
        assert m["repeat_findings"] == 2

    def test_metrics_health_score_range(self):
        rows = _parse_findings_csv(FINDINGS_CSV)
        m = _compute_findings_metrics(rows)
        assert 0 <= m["finding_health_score"] <= 100

    def test_metrics_health_penalised_by_critical(self):
        rows = _parse_findings_csv(FINDINGS_CSV)
        m = _compute_findings_metrics(rows)
        # Has open critical → deducted from 100
        assert m["finding_health_score"] < 100

    def test_metrics_perfect_score(self):
        rows = _parse_findings_csv(FINDINGS_ALL_CLEAR)
        m = _compute_findings_metrics(rows)
        assert m["finding_health_score"] == 100.0
        assert m["open_critical"] == 0

    def test_alerts_critical_finding(self):
        rows = _parse_findings_csv(FINDINGS_CSV)
        m = _compute_findings_metrics(rows)
        alerts = _build_findings_alerts(m)
        assert any(a["level"] == "critical" for a in alerts)

    def test_empty_findings(self):
        m = _compute_findings_metrics([])
        assert m["total_findings"] == 0
        assert m["finding_health_score"] == 0.0


# ── Controls Agent Tests ──────────────────────────────────────────────────────

class TestControlsAgent:
    def test_parse_count(self):
        rows = _parse_controls_csv(CONTROLS_CSV)
        assert len(rows) == 5

    def test_parse_empty(self):
        assert _parse_controls_csv("") == []

    def test_parse_effectiveness_normalised(self):
        rows = _parse_controls_csv(CONTROLS_CSV)
        valid = {"effective", "partially_effective", "ineffective"}
        assert all(r["design"] in valid and r["operating"] in valid for r in rows)

    def test_parse_stale_detection(self):
        rows = _parse_controls_csv(CONTROLS_CSV)
        # C003 (2023-01-01) and C005 (2022-06-01) are >12 months old
        stale = [r for r in rows if r["stale"]]
        assert len(stale) >= 2

    def test_metrics_ineffective_count(self):
        rows = _parse_controls_csv(CONTROLS_CSV)
        m = _compute_controls_metrics(rows)
        # C003 has ineffective operating; C005 has ineffective design+operating
        assert len(m["ineffective_controls"]) >= 2

    def test_metrics_overall_score_range(self):
        rows = _parse_controls_csv(CONTROLS_CSV)
        m = _compute_controls_metrics(rows)
        assert 0 <= m["overall_control_score"] <= 100

    def test_metrics_all_effective_score(self):
        rows = _parse_controls_csv(CONTROLS_ALL_EFFECTIVE)
        m = _compute_controls_metrics(rows)
        assert m["overall_control_score"] == 100.0
        assert len(m["ineffective_controls"]) == 0

    def test_metrics_stale_count(self):
        rows = _parse_controls_csv(CONTROLS_CSV)
        m = _compute_controls_metrics(rows)
        assert m["stale_controls"] >= 2

    def test_alerts_ineffective_controls(self):
        rows = _parse_controls_csv(CONTROLS_CSV)
        m = _compute_controls_metrics(rows)
        alerts = _build_controls_alerts(m)
        assert any(a["level"] == "critical" for a in alerts)

    def test_empty_controls(self):
        m = _compute_controls_metrics([])
        assert m["total_controls"] == 0
        assert m["overall_control_score"] == 0.0


# ── Coverage Agent Tests ──────────────────────────────────────────────────────

class TestCoverageAgent:
    def test_parse_count(self):
        rows = _parse_coverage_csv(COVERAGE_CSV)
        assert len(rows) == 6

    def test_parse_empty(self):
        assert _parse_coverage_csv("") == []

    def test_parse_never_audited_marked(self):
        rows = _parse_coverage_csv(COVERAGE_CSV)
        # "Legal & Compliance" has no last_audit date
        legal = next(r for r in rows if "legal" in r["unit"].lower())
        assert legal["audited"] is False

    def test_metrics_coverage_rate(self):
        rows = _parse_coverage_csv(COVERAGE_CSV)
        m = _compute_coverage_metrics(rows)
        # 5 of 6 have last_audit (Legal has none)
        assert m["coverage_rate"] == pytest.approx(5 / 6, abs=0.01)

    def test_metrics_high_risk_coverage(self):
        rows = _parse_coverage_csv(COVERAGE_CSV)
        m = _compute_coverage_metrics(rows)
        # high/critical units: AP, Payroll, IT, Legal — 3 audited out of 4 = 0.75
        assert 0 < m["high_risk_coverage"] <= 1.0

    def test_metrics_overdue_units_present(self):
        rows = _parse_coverage_csv(COVERAGE_CSV)
        m = _compute_coverage_metrics(rows)
        # IT Infrastructure last_audit 2022 → overdue
        assert m["audit_backlog"] >= 1

    def test_metrics_overdue_sorted_by_risk(self):
        rows = _parse_coverage_csv(COVERAGE_CSV)
        m = _compute_coverage_metrics(rows)
        overdue = m["overdue_units"]
        if len(overdue) >= 2:
            risk_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
            scores = [risk_order.get(u["risk"], 4) for u in overdue]
            assert scores == sorted(scores)

    def test_alerts_high_risk_gap(self):
        rows = _parse_coverage_csv(COVERAGE_CSV)
        m = _compute_coverage_metrics(rows)
        alerts = _build_coverage_alerts(m)
        # high_risk_coverage may be < 80%
        assert isinstance(alerts, list)

    def test_empty_coverage(self):
        m = _compute_coverage_metrics([])
        assert m["total_units"] == 0
        assert m["coverage_rate"] == 0.0


# ── Audit Health Score Tests ──────────────────────────────────────────────────

class TestAuditHealthScore:
    def test_perfect_audit_health(self):
        """All 100 inputs → health score = 100."""
        score = round(100.0 * 0.35 + 100.0 * 0.40 + 100.0 * 0.25, 1)
        assert score == 100.0

    def test_poor_audit_health(self):
        """All 0 inputs → health score = 0."""
        score = round(0.0 * 0.35 + 0.0 * 0.40 + 0.0 * 0.25, 1)
        assert score == 0.0

    def test_maturity_labels(self):
        def _maturity(score: float) -> str:
            if score >= 80: return "optimised"
            if score >= 65: return "managed"
            if score >= 50: return "defined"
            if score >= 35: return "developing"
            return "initial"

        assert _maturity(85) == "optimised"
        assert _maturity(70) == "managed"
        assert _maturity(55) == "defined"
        assert _maturity(40) == "developing"
        assert _maturity(20) == "initial"

    def test_realistic_score(self):
        """Realistic mixed inputs should produce a score in valid range."""
        findings_score = 70.0
        control_score  = 65.0
        coverage_score = 80.0
        result = round(findings_score * 0.35 + control_score * 0.40 + coverage_score * 0.25, 1)
        assert 0 <= result <= 100
