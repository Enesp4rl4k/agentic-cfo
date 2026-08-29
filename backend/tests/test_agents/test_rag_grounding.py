"""Tests for RAG grounding validator."""

from __future__ import annotations

from app.platform.contracts import EvidenceBundle, EvidenceCitation
from app.services.rag.grounding_validator import (
    apply_disclaimer,
    no_evidence_verdict,
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
                preview="cash balance 500.000 TL",
            )
        ],
    )
    verdict = validate_grounding("Nakit 500.000 TL.", bundle)
    assert verdict.grounded is True


def test_invented_amount_with_unrelated_evidence_is_not_grounded() -> None:
    bundle = EvidenceBundle(
        query="nakit",
        org_id="org-1",
        citations=[
            EvidenceCitation(
                job_id="j1",
                chunk_index=0,
                source_type="cfo_transactions_raw",
                score=0.5,
                preview="office rent 12.000 TL",
            )
        ],
    )
    verdict = validate_grounding("Nakit 9.999.999 TL.", bundle)
    assert verdict.grounded is False
    assert verdict.requires_disclaimer is True
    assert verdict.flagged_claims


def test_amount_with_semantic_metrics_is_grounded() -> None:
    verdict = validate_grounding(
        "Runway is 8.5 months.",
        None,
        semantic_metrics={"finance.runway_months": 8.5},
    )
    assert verdict.grounded is True
    assert verdict.requires_disclaimer is False


def test_no_evidence_verdict_requires_disclaimer() -> None:
    verdict = no_evidence_verdict()
    assert verdict.requires_disclaimer is True
    assert "No RAG evidence" in verdict.reasons[0]
    out = apply_disclaimer("Cevap metni.", verdict, locale="tr")
    assert "doğrulanmamıştır" in out or "kanıt" in out.lower()


def test_evidence_bundle_merge_dedupes() -> None:
    a = EvidenceBundle(
        query="q",
        org_id="org-1",
        citations=[
            EvidenceCitation("j1", 0, "cfo_transactions_raw", 0.9, "tx row"),
        ],
        retriever_version="tfidf_v1",
    )
    b = EvidenceBundle(
        query="q",
        org_id="org-1",
        citations=[
            EvidenceCitation("s1", 0, "semantic_snapshot", 0.8, "finance.revenue=100"),
        ],
        retriever_version="pgvector_v2",
    )
    merged = a.merge(b, top_k=4)
    assert len(merged.citations) == 2
    assert merged.found is True
    assert "tfidf_v1+pgvector_v2" in merged.retriever_version
