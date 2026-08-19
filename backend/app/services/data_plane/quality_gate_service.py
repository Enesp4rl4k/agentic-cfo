from __future__ import annotations

from dataclasses import dataclass


@dataclass
class QualityGateResult:
    quality_score: float
    issues: list[str]
    should_block: bool
    should_review: bool


def score_sync_quality(
    *,
    validator_health_score: int,
    canonical_row_count: int,
) -> QualityGateResult:
    """
    Unified data-plane quality score in 0..1.
    """
    issues: list[str] = []
    score = max(0.0, min(1.0, validator_health_score / 100.0))

    if canonical_row_count == 0:
        score = 0.0
        issues.append("no_canonical_rows")
    elif canonical_row_count < 5:
        score = min(score, 0.75)
        issues.append("low_row_count")

    should_block = score < 0.50
    should_review = (not should_block) and score < 0.80
    return QualityGateResult(
        quality_score=round(score, 4),
        issues=issues,
        should_block=should_block,
        should_review=should_review,
    )

