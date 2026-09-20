"""Tests for offline grounding eval (hallucinated numbers)."""

from __future__ import annotations

from app.services.eval_harness import GOLDEN_CASES, run_grounding_eval, score_case
from app.services.semantic.conflicts import detect_metric_conflicts
from app.services.semantic.types import MetricPoint


def test_grounding_eval_golden_suite_passes() -> None:
    report = run_grounding_eval()
    assert report.failed == 0, report.to_dict()
    assert report.hallucination_cases == 0
    assert report.pass_rate == 1.0
    assert report.total == len(GOLDEN_CASES)


def test_invented_cash_case_is_caught() -> None:
    case = next(c for c in GOLDEN_CASES if c.case_id == "invented_cash_balance")
    result = score_case(case)
    assert result.passed is True
    assert result.actual_grounded is False
    assert result.flagged_claims


def test_revenue_vs_canonical_inflow_conflict() -> None:
    metrics = [
        MetricPoint("finance.revenue", 1_000_000, "cents", source_agent="cfo"),
        MetricPoint(
            "finance.canonical_inflow",
            400_000,
            "cents",
            source_agent="canonical",
            data_source="canonical",
        ),
    ]
    conflicts = detect_metric_conflicts(metrics)
    assert any(c["topic"] == "revenue_vs_canonical_inflow" for c in conflicts)


def test_growth_vs_cash_conflict() -> None:
    metrics = [
        MetricPoint("growth.overall_roas", 4.2, "ratio", source_agent="cmo"),
        MetricPoint("finance.runway_months", 2.0, "months", source_agent="cfo"),
    ]
    conflicts = detect_metric_conflicts(metrics)
    assert any(c["topic"] == "growth_vs_cash" for c in conflicts)


def test_aligned_metrics_have_no_conflict() -> None:
    metrics = [
        MetricPoint("finance.revenue", 1_000_000, "cents", source_agent="cfo"),
        MetricPoint("finance.canonical_inflow", 980_000, "cents", data_source="canonical"),
        MetricPoint("growth.overall_roas", 2.0, "ratio", source_agent="cmo"),
        MetricPoint("finance.runway_months", 10.0, "months", source_agent="cfo"),
    ]
    assert detect_metric_conflicts(metrics) == []
