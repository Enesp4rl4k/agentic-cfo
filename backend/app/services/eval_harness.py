"""Offline grounding eval — did the agent invent numbers?

Runs without an LLM. Golden answers are scored by the same validator
that gates production chat.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.platform.contracts import EvidenceBundle, EvidenceCitation
from app.services.rag.grounding_validator import (
    extract_numeric_claims,
    validate_grounding,
)


@dataclass(frozen=True)
class GoldenCase:
    case_id: str
    answer: str
    expect_grounded: bool
    semantic_metrics: dict[str, float | int | str | bool | None] = field(default_factory=dict)
    evidence_previews: list[str] = field(default_factory=list)


@dataclass
class CaseResult:
    case_id: str
    passed: bool
    expect_grounded: bool
    actual_grounded: bool
    flagged_claims: list[str]
    claim_count: int


@dataclass
class EvalReport:
    passed: int
    failed: int
    hallucination_cases: int
    results: list[CaseResult]

    @property
    def total(self) -> int:
        return self.passed + self.failed

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 1.0

    def to_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "failed": self.failed,
            "pass_rate": round(self.pass_rate, 4),
            "hallucination_cases": self.hallucination_cases,
            "results": [
                {
                    "case_id": r.case_id,
                    "passed": r.passed,
                    "expect_grounded": r.expect_grounded,
                    "actual_grounded": r.actual_grounded,
                    "flagged_claims": r.flagged_claims,
                }
                for r in self.results
            ],
        }


GOLDEN_CASES: list[GoldenCase] = [
    GoldenCase(
        case_id="faithful_runway",
        answer="Cash runway is 8.5 months.",
        semantic_metrics={"finance.runway_months": 8.5},
        expect_grounded=True,
    ),
    GoldenCase(
        case_id="faithful_revenue_from_evidence",
        answer="Dönem geliri 1.250.000 TL.",
        evidence_previews=["canonical inflow 1.250.000 TL from closed invoices"],
        semantic_metrics={"finance.revenue": 1_250_000},
        expect_grounded=True,
    ),
    GoldenCase(
        case_id="invented_cash_balance",
        answer="Nakit 9.999.999 TL seviyesinde.",
        evidence_previews=["office rent 12.000 TL"],
        semantic_metrics={"finance.revenue": 1_250_000, "finance.runway_months": 8.5},
        expect_grounded=False,
    ),
    GoldenCase(
        case_id="no_evidence_numeric",
        answer="Revenue is 500000 USD.",
        expect_grounded=False,
    ),
    GoldenCase(
        case_id="qualitative_ok",
        answer="Liquidity looks tight; I would review collections before hiring.",
        semantic_metrics={"finance.runway_months": 4.0},
        expect_grounded=True,
    ),
]


def _bundle(previews: list[str]) -> EvidenceBundle | None:
    if not previews:
        return None
    citations = [
        EvidenceCitation(
            job_id="eval",
            chunk_index=i,
            source_type="cfo_transactions_raw",
            score=0.9,
            preview=preview,
        )
        for i, preview in enumerate(previews)
    ]
    return EvidenceBundle(query="eval", org_id="eval-org", citations=citations)


def score_case(case: GoldenCase) -> CaseResult:
    verdict = validate_grounding(
        case.answer,
        _bundle(case.evidence_previews),
        semantic_metrics=case.semantic_metrics or None,
    )
    passed = verdict.grounded is case.expect_grounded
    return CaseResult(
        case_id=case.case_id,
        passed=passed,
        expect_grounded=case.expect_grounded,
        actual_grounded=verdict.grounded,
        flagged_claims=list(verdict.flagged_claims),
        claim_count=len(extract_numeric_claims(case.answer)),
    )


def run_grounding_eval(cases: list[GoldenCase] | None = None) -> EvalReport:
    """Score golden cases. hallucination_cases = invented-number cases that failed to catch."""
    results = [score_case(c) for c in (cases or GOLDEN_CASES)]
    passed = sum(1 for r in results if r.passed)
    failed = len(results) - passed
    hallucination_misses = sum(
        1
        for r, c in zip(results, cases or GOLDEN_CASES, strict=False)
        if c.expect_grounded is False and r.actual_grounded is True
    )
    return EvalReport(
        passed=passed,
        failed=failed,
        hallucination_cases=hallucination_misses,
        results=results,
    )


# ── Confidence-gate calibration ──────────────────────────────────────────────
#
# The confidence gate (CONFIDENCE_AUTO_PROCEED_MIN) is only load-bearing if the
# confidence number tracks correctness. With a labeled set of (min_confidence,
# was_the_output_actually_correct) observations we can measure:
#
#   precision@threshold — of the runs the gate let through, how many were correct
#   recall@threshold    — of the correct runs, how many the gate let through
#
# CI asserts precision@threshold == 1.0: the gate must never auto-proceed a wrong
# result on the labeled set. Recall is reported, not gated (a strict gate that
# holds some good runs for review is acceptable; letting a bad one through is not).

@dataclass(frozen=True)
class ConfidenceObservation:
    label: str
    min_confidence: float
    correct: bool
    # True  → this run SHOULD have auto-proceeded (a known-good input).
    # False → this run SHOULD have been held (garbage / low-quality input).
    should_proceed: bool = True


@dataclass
class CalibrationReport:
    threshold: float
    proceeded_total: int          # runs with confidence >= threshold
    proceeded_correct: int
    held_total: int               # runs with confidence < threshold
    held_correct: int             # correct runs the gate held back (recall loss)
    observations: list[ConfidenceObservation]

    @property
    def precision_at_threshold(self) -> float:
        """Of the runs the gate let through, how many were actually good."""
        return self.proceeded_correct / self.proceeded_total if self.proceeded_total else 1.0

    @property
    def recall_at_threshold(self) -> float:
        """Of the runs that SHOULD have proceeded, how many the gate let through."""
        should = [o for o in self.observations if o.should_proceed]
        if not should:
            return 1.0
        let_through = sum(1 for o in should if o.min_confidence >= self.threshold)
        return let_through / len(should)

    @property
    def specificity_at_threshold(self) -> float:
        """Of the runs that SHOULD have been held, how many the gate held."""
        should_hold = [o for o in self.observations if not o.should_proceed]
        if not should_hold:
            return 1.0
        held = sum(1 for o in should_hold if o.min_confidence < self.threshold)
        return held / len(should_hold)

    def to_dict(self) -> dict[str, object]:
        return {
            "threshold": self.threshold,
            "precision_at_threshold": round(self.precision_at_threshold, 4),
            "recall_at_threshold": round(self.recall_at_threshold, 4),
            "specificity_at_threshold": round(self.specificity_at_threshold, 4),
            "proceeded": f"{self.proceeded_correct}/{self.proceeded_total}",
            "held_but_correct": self.held_correct,
        }


def calibrate_confidence_gate(
    observations: list[ConfidenceObservation],
    *,
    threshold: float,
) -> CalibrationReport:
    proceeded = [o for o in observations if o.min_confidence >= threshold]
    held = [o for o in observations if o.min_confidence < threshold]
    return CalibrationReport(
        threshold=threshold,
        proceeded_total=len(proceeded),
        proceeded_correct=sum(1 for o in proceeded if o.correct),
        held_total=len(held),
        held_correct=sum(1 for o in held if o.correct),
        observations=list(observations),
    )
