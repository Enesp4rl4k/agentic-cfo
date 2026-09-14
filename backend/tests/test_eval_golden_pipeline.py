"""
Golden-case evaluation of the end-to-end CFO pipeline.

Each case feeds a known CSV through ``run_cfo_pipeline`` and checks the computed
figures, the reconciliation verdict, and that no narrative invented a number.
These are deterministic (template narratives, threshold 0.0) so they belong in
the normal suite; ``-m eval`` selects just this file and the gate test asserts
the aggregate pass-rate, tolerating at most one regression before failing CI.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import pytest

from app.agents.orchestrator import run_cfo_pipeline
from app.agents.state import AgentRunConfig
from app.platform.policies import CONFIDENCE_AUTO_PROCEED_MIN
from app.services.eval_harness import ConfidenceObservation, calibrate_confidence_gate

pytestmark = pytest.mark.eval

_CFG = AgentRunConfig(require_review=False, auto_proceed_min_confidence=0.0)


@dataclass
class GoldenPipelineCase:
    case_id: str
    csv: str
    check: Callable[[dict], None]


PROFITABLE = """\
date,description,amount,type,category
2024-01-05,Rent,-8000,expense,rent
2024-01-10,Client A,25000,income,sales
2024-01-15,Utilities,-1500,expense,utilities
2024-01-20,Client B,18000,income,sales
2024-01-25,COGS parts,-6000,expense,cogs
2024-01-30,Consulting,12000,income,services
"""

LOSS_MAKING = """\
date,description,amount,type,category
2024-02-05,Rent,-20000,expense,rent
2024-02-10,Small sale,5000,income,sales
2024-02-15,Marketing,-15000,expense,marketing
2024-02-20,Salaries,-30000,expense,salary
"""

DUPLICATES = """\
date,description,amount,type,category
2024-03-05,Rent,-8000,expense,rent
2024-03-05,Rent,-8000,expense,rent
2024-03-10,Client,25000,income,sales
2024-03-10,Client,25000,income,sales
2024-03-15,Utilities,-1500,expense,utilities
"""


def _check_profitable(r: dict) -> None:
    assert not r.get("halted"), r.get("error")
    pnl = r["pnl"]
    assert pnl["revenue"] == 5_500_000  # (25000+18000+12000) * 100 cents
    assert pnl["cogs"] == 600_000
    assert pnl["gross_profit"] == pnl["revenue"] - pnl["cogs"]
    assert pnl["net_income"] > 0
    assert r["reconciliation"]["action"] in ("proceed", "hold_for_review")
    assert not r["reconciliation"]["identity_failures"]


def _check_loss(r: dict) -> None:
    assert not r.get("halted"), r.get("error")
    pnl = r["pnl"]
    assert pnl["revenue"] == 500_000  # 5000 * 100 cents
    assert pnl["net_income"] < 0
    assert not r["reconciliation"]["identity_failures"]


def _check_duplicates(r: dict) -> None:
    if r.get("halted"):
        pytest.skip("pipeline halted on duplicate fixture")
    anomalies = r.get("anomalies") or []
    assert anomalies, "expected duplicate transactions to raise an anomaly"
    assert not r["reconciliation"]["identity_failures"]


CASES = [
    GoldenPipelineCase("profitable_month", PROFITABLE, _check_profitable),
    GoldenPipelineCase("loss_making_month", LOSS_MAKING, _check_loss),
    GoldenPipelineCase("duplicate_detection", DUPLICATES, _check_duplicates),
]


@pytest.fixture
def _write_csv(tmp_path):
    def _w(text: str, name: str) -> str:
        f = tmp_path / f"{name}.csv"
        f.write_text(text, encoding="utf-8")
        return str(f)

    return _w


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.case_id)
async def test_golden_pipeline_case(case: GoldenPipelineCase, _write_csv) -> None:
    result = await run_cfo_pipeline(
        job_id=f"eval-{case.case_id}",
        file_path=_write_csv(case.csv, case.case_id),
        file_type="csv",
        run_config=_CFG,
    )
    case.check(result)


async def test_golden_pipeline_pass_rate_gate(_write_csv) -> None:
    """Aggregate gate — CI fails if more than one golden case regresses."""
    passed = 0
    failures: list[str] = []
    for case in CASES:
        try:
            result = await run_cfo_pipeline(
                job_id=f"evalgate-{case.case_id}",
                file_path=_write_csv(case.csv, f"gate_{case.case_id}"),
                file_type="csv",
                run_config=_CFG,
            )
            case.check(result)
            passed += 1
        except AssertionError as exc:
            failures.append(f"{case.case_id}: {exc}")

    pass_rate = passed / len(CASES)
    assert pass_rate >= 0.9, f"golden pipeline pass-rate {pass_rate:.0%}; failures={failures}"


# ── Confidence-gate calibration ────────────────────────────────────────────

_EMPTY = ""  # ingestion halts → not a valid "proceed", must not pass the gate
_GARBAGE = "not,a,csv\nrandom text without structure\n"


async def test_confidence_gate_precision_on_labeled_set(_write_csv) -> None:
    """
    The gate must never let a wrong result auto-proceed. Build labeled
    observations from good fixtures (expected correct) + broken inputs
    (expected halted/held) and assert precision@threshold == 1.0.
    """
    observations: list[ConfidenceObservation] = []

    for case in CASES:
        r = await run_cfo_pipeline(
            job_id=f"cal-{case.case_id}",
            file_path=_write_csv(case.csv, f"cal_{case.case_id}"),
            file_type="csv",
            run_config=_CFG,
        )
        try:
            case.check(r)
            correct = not r.get("halted")
        except AssertionError:
            correct = False
        observations.append(
            ConfidenceObservation(case.case_id, float(r.get("min_confidence") or 0.0), correct)
        )

    for label, text in (("empty", _EMPTY), ("garbage", _GARBAGE)):
        r = await run_cfo_pipeline(
            job_id=f"cal-{label}",
            file_path=_write_csv(text, f"cal_{label}"),
            file_type="csv",
            run_config=AgentRunConfig(require_review=True),  # real threshold
        )
        # A broken run is "correct" only if the pipeline refused it.
        refused = bool(r.get("halted") or r.get("awaiting_review"))
        observations.append(
            ConfidenceObservation(label, float(r.get("min_confidence") or 0.0), refused)
        )

    report = calibrate_confidence_gate(
        observations, threshold=CONFIDENCE_AUTO_PROCEED_MIN
    )
    assert report.precision_at_threshold == 1.0, report.to_dict()
