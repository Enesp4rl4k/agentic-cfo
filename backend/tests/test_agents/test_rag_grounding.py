"""Tests for RAG grounding validator."""

from __future__ import annotations

from app.platform.contracts import EvidenceBundle, EvidenceCitation
from app.services.rag.grounding_validator import (
    apply_disclaimer,
    validate_grounding,
)


def test_no_amounts_is_grounded() -> None:
    verdict = validate_grounding("Genel durum iyi görünüyor.", None)
    assert verdict.grounded is True
    assert verdict.requires_disclaimer is False


def test_amount_without_evidence_requires_disclaimer() -> None:
    verdict = validate_grounding("Nakit 1.250.000 TL seviyesinde.", None)
    assert verdict.grounded is False
    assert verdict.requires_disclaimer is True
    assert verdict.flagged_claims


def test_amount_with_evidence_is_grounded() -> None:
    bundle = EvidenceBundle(
        query="nakit",
        org_id="org-1",
        citations=[
            EvidenceCitation(
                job_id="j1",
                chunk_index=0,
                source_type="cfo_transactions_raw",
                score=0.5,
                preview="cash balance",
            )
        ],
    )
    verdict = validate_grounding("Nakit 500.000 TL.", bundle)
    assert verdict.grounded is True


def test_apply_disclaimer_appends_text() -> None:
    from app.services.rag.grounding_validator import GroundingVerdict

    verdict = GroundingVerdict(grounded=False, requires_disclaimer=True)
    out = apply_disclaimer("Tahmin: 10% artış.", verdict, locale="tr")
    assert "doğrulanmamıştır" in out.lower() or "kanıt" in out.lower()
