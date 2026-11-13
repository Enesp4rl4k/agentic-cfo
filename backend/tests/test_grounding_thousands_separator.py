"""A Turkish amount writes its thousands with a dot: "50.000 TL" is fifty thousand.

Read as 50.0, a correct answer ("285.000 TL") was flagged as unsupported by the
evidence "285000.00", and the grounding gate could not tell a true figure from an
invented one.
"""

from __future__ import annotations

import pytest

from app.platform.contracts import EvidenceBundle, EvidenceCitation
from app.services.rag.grounding_validator import (
    extract_numeric_claims,
    parse_numeric_token,
    validate_grounding,
)


@pytest.mark.parametrize(
    ("raw", "value"),
    [
        ("50.000", 50_000.0),
        ("285.000", 285_000.0),
        ("1.234.567", 1_234_567.0),
        ("12.345,67", 12_345.67),
        ("1,234.56", 1_234.56),
        ("3.5", 3.5),
        ("0.25", 0.25),
        ("19,99", 19.99),
    ],
)
def test_amounts_are_read_the_way_they_are_written(raw, value):
    assert parse_numeric_token(raw) == pytest.approx(value)


def test_a_dotted_amount_in_an_answer_is_a_claim_of_that_size():
    assert extract_numeric_claims("Alacağınız 285.000 TL tutarındadır.") == [285_000.0]


def test_a_true_dotted_figure_is_supported_by_the_ledger_evidence():
    evidence = EvidenceBundle(
        query="alacak", org_id="o",
        citations=[EvidenceCitation(job_id=None, chunk_index=1, source_type="ledger_row", score=1.0,
                                    preview="2024-02-01 income 285000.00 TRY ABC Holding")],
    )
    verdict = validate_grounding("ABC Holding'den 285.000 TL alacağınız var.", evidence)
    assert verdict.grounded and not verdict.flagged_claims


def test_an_invented_dotted_figure_is_still_flagged():
    evidence = EvidenceBundle(
        query="alacak", org_id="o",
        citations=[EvidenceCitation(job_id=None, chunk_index=1, source_type="ledger_row", score=1.0,
                                    preview="2024-02-01 income 285000.00 TRY ABC Holding")],
    )
    verdict = validate_grounding("ABC Holding'den 920.000 TL alacağınız var.", evidence)
    assert not verdict.grounded
