"""Confidence decomposition (differentiator #6)."""
from __future__ import annotations

from app.agents.confidence_breakdown import build_confidence_breakdown
from app.agents.state import StepLog


def _state(**kw):
    base = {"logs": [], "min_confidence": 1.0}
    base.update(kw)
    return base


def test_identifies_binding_constraint():
    state = _state(logs=[
        StepLog(step="data_ingestion", ok=True, detail="12 rows", confidence=0.95),
        StepLog(step="pnl", ok=True, detail="clean", confidence=0.9),
        StepLog(step="forecast", ok=True, detail="only 3 months history", confidence=0.62),
        StepLog(step="tax", ok=True, confidence=0.88),
    ])
    b = build_confidence_breakdown(state, threshold=0.80)

    assert b["aggregate"] == 0.62
    assert b["binding_constraint"] == "forecast"
    assert b["meets_threshold"] is False
    weakest = [c for c in b["components"] if c["weakest"]]
    assert len(weakest) == 1 and weakest[0]["step"] == "forecast"
    assert "forecast" in b["narrative"]
    assert "3 months history" in b["narrative"]


def test_echo_steps_excluded():
    state = _state(logs=[
        StepLog(step="pnl", ok=True, confidence=0.9),
        StepLog(step="verifier", ok=True, confidence=0.9),   # echo — excluded
        StepLog(step="report", ok=True, confidence=1.0),     # echo — excluded
    ])
    b = build_confidence_breakdown(state)
    assert [c["step"] for c in b["components"]] == ["pnl"]


def test_reflection_and_reconciliation_fold_in():
    state = _state(
        logs=[StepLog(step="pnl", ok=True, confidence=0.92)],
        reflection_scores={"forecast": {"overall_score": 0.4}},
        reconciliation={"action": "halt",
                        "identity_failures": ["revenue != sum(income)"]},
    )
    b = build_confidence_breakdown(state, threshold=0.80)
    steps = {c["step"] for c in b["components"]}
    assert "reflection:forecast" in steps
    assert "reconciliation" in steps
    assert b["binding_constraint"] == "reconciliation"  # halt → 0.0 < everything
    assert b["aggregate"] == 0.0


def test_meets_threshold_when_all_high():
    state = _state(logs=[
        StepLog(step="pnl", ok=True, confidence=0.95),
        StepLog(step="cashflow", ok=True, confidence=0.9),
    ])
    b = build_confidence_breakdown(state, threshold=0.80)
    assert b["meets_threshold"] is True
    assert "Eşiği geçiyor" in b["narrative"]


def test_no_components_is_safe():
    b = build_confidence_breakdown(_state(min_confidence=0.7), threshold=0.8)
    assert b["components"] == []
    assert b["aggregate"] == 0.7
    assert b["binding_constraint"] is None
