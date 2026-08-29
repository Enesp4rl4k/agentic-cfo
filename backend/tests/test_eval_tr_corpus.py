"""
End-to-end golden eval over the real-shaped TR fixture corpus.

Runs each fixture through the full CFO pipeline (and the UBL-TR parser) and
asserts the computed P&L, reconciliation verdict and anomaly detection against
hand-derived expectations. Also builds a confidence-vs-correctness observation
set and asserts the gate's precision on it.

Marked ``eval`` so ``pytest -m eval`` (a CI gate) selects it.
"""
from __future__ import annotations

import pytest

from app.agents.orchestrator import run_cfo_pipeline
from app.agents.state import AgentRunConfig
from app.parsers.invoice.ubl_tr import UBLTRInvoiceParser
from app.platform.policies import CONFIDENCE_AUTO_PROCEED_MIN
from app.services.eval_harness import ConfidenceObservation, calibrate_confidence_gate
from tests.fixtures.tr_corpus import expectations as EXP

pytestmark = pytest.mark.eval

_CFG = AgentRunConfig(require_review=False, auto_proceed_min_confidence=0.0)


async def _run(case: dict):
    return await run_cfo_pipeline(
        job_id=f"trcorpus-{case['file']}",
        file_path=str(EXP.CORPUS_DIR / case["file"]),
        file_type="csv",
        run_config=_CFG,
    )


def _assert_pnl(result: dict, case: dict) -> None:
    assert result.get("halted") is case["expect_halted"], result.get("error")
    pnl = result["pnl"]
    for key, expected in case["pnl"].items():
        assert pnl[key] == expected, f"{case['file']} pnl.{key}: {pnl[key]} != {expected}"

    if "net_margin_min" in case:
        assert pnl["net_margin"] >= case["net_margin_min"]
    if "net_margin_max" in case:
        assert pnl["net_margin"] <= case["net_margin_max"]

    recon = result.get("reconciliation") or {}
    assert not recon.get("identity_failures"), recon
    assert recon.get("action") == case["reconciliation_action"]

    flagged = {a.get("anomaly_type") for a in (result.get("anomalies") or [])}
    missing = case["must_flag_anomaly_types"] - flagged
    assert not missing, f"{case['file']}: expected anomaly types {missing}, got {flagged}"


@pytest.mark.parametrize("case", EXP.CSV_CASES, ids=lambda c: c["file"])
async def test_tr_corpus_csv_case(case: dict) -> None:
    _assert_pnl(await _run(case), case)


def test_tr_corpus_efatura_ubl_tr() -> None:
    xml = (EXP.CORPUS_DIR / EXP.EFATURA["file"]).read_text(encoding="utf-8")
    parsed = UBLTRInvoiceParser.parse_xml(xml)

    assert parsed.invoice_number == EXP.EFATURA["invoice_number"]
    assert parsed.supplier.vkn_tckn == EXP.EFATURA["supplier_vkn"]
    assert parsed.line_extension_total == EXP.EFATURA["line_extension_total"]
    assert parsed.payable_amount == EXP.EFATURA["payable_amount"]

    by_code = {e.account_code: e for e in parsed.suggested_tdhp_entries}
    for code, (debit, credit) in EXP.EFATURA["tdhp"].items():
        assert code in by_code, f"missing TDHP account {code}"
        assert by_code[code].debit_amount == debit
        assert by_code[code].credit_amount == credit

    # double-entry must balance
    total_debit = sum(e.debit_amount for e in parsed.suggested_tdhp_entries)
    total_credit = sum(e.credit_amount for e in parsed.suggested_tdhp_entries)
    assert total_debit == total_credit


async def test_bozuk_veri_is_held_by_the_gate() -> None:
    """A file where every date is unparseable must not auto-proceed."""
    result = await run_cfo_pipeline(
        job_id="trcorpus-bozuk",
        file_path=str(EXP.CORPUS_DIR / EXP.BOZUK["file"]),
        file_type="csv",
        run_config=AgentRunConfig(require_review=True),  # real threshold
    )
    assert result.get("halted") or result.get("awaiting_review"), result
    assert float(result.get("min_confidence") or 1.0) < CONFIDENCE_AUTO_PROCEED_MIN


async def test_tr_corpus_confidence_calibration() -> None:
    """
    Build a labeled (confidence, correct) set from the corpus — good months that
    must proceed + a garbage file that must be held — and assert the gate's
    precision AND recall at the 0.80 threshold are both 1.0. A regression that
    over-scores garbage (recall/precision drop) or under-scores a good run
    (recall drop) breaks this.
    """
    observations: list[ConfidenceObservation] = []

    for case in EXP.CSV_CASES:
        result = await _run(case)
        try:
            _assert_pnl(result, case)
            correct = case["correct"] and not result.get("halted")
        except AssertionError:
            correct = False
        observations.append(
            ConfidenceObservation(
                case["file"], float(result.get("min_confidence") or 0.0), correct
            )
        )

    # Garbage file: "correct" == the gate refused it.
    bad = await run_cfo_pipeline(
        job_id="trcorpus-bozuk-cal",
        file_path=str(EXP.CORPUS_DIR / EXP.BOZUK["file"]),
        file_type="csv",
        run_config=AgentRunConfig(require_review=True),
    )
    refused = bool(bad.get("halted") or bad.get("awaiting_review"))
    observations.append(
        ConfidenceObservation(
            "bozuk_veri.csv",
            float(bad.get("min_confidence") or 0.0),
            correct=refused,
            should_proceed=False,
        )
    )

    report = calibrate_confidence_gate(observations, threshold=CONFIDENCE_AUTO_PROCEED_MIN)
    print("confidence calibration:", report.to_dict())  # curve for CI logs
    assert report.precision_at_threshold == 1.0, report.to_dict()
    assert report.recall_at_threshold == 1.0, report.to_dict()
    assert report.specificity_at_threshold == 1.0, report.to_dict()
