"""Tests for shared chat grounding helpers."""

from __future__ import annotations

from app.platform.contracts import EvidenceBundle, EvidenceCitation
from app.services.chat_grounding import GroundedChatPack, finalize_grounded_answer


def test_grounded_chat_pack_to_meta() -> None:
    pack = GroundedChatPack(
        system_prompt="base",
        evidence_found=True,
        evidence_tx_count=2,
        evidence_semantic_count=1,
        retriever_version="hybrid_v1",
        semantic_values={"finance.revenue": 100},
    )
    meta = pack.to_meta()
    assert meta["evidence_found"] is True
    assert meta["evidence_tx_count"] == 2
    assert meta["evidence_semantic_count"] == 1
    assert meta["evidence_retriever_version"] == "hybrid_v1"


def test_finalize_no_evidence_no_semantic_adds_disclaimer() -> None:
    pack = GroundedChatPack(
        system_prompt="base",
        evidence_found=False,
        evidence_tx_count=0,
        evidence_semantic_count=0,
        retriever_version="none",
        semantic_values={},
    )
    text, validated = finalize_grounded_answer("Cevap metni.", pack, locale="tr")
    assert validated is False
    assert "doğrulanmamıştır" in text or "kanıt" in text.lower()


def test_finalize_with_semantic_metrics_skips_no_evidence_path() -> None:
    pack = GroundedChatPack(
        system_prompt="base",
        evidence_found=False,
        evidence_tx_count=0,
        evidence_semantic_count=0,
        retriever_version="none",
        semantic_values={"finance.runway_months": 8.5},
    )
    text, validated = finalize_grounded_answer("Runway is stable.", pack, locale="en")
    assert validated is True
    assert text == "Runway is stable."


def test_finalize_with_evidence_and_ungrounded_amount() -> None:
    bundle = EvidenceBundle(
        query="nakit",
        org_id="org-1",
        citations=[
            EvidenceCitation("j1", 0, "cfo_transactions_raw", 0.5, "cash"),
        ],
    )
    pack = GroundedChatPack(
        system_prompt="base",
        evidence_found=True,
        evidence_tx_count=1,
        evidence_semantic_count=0,
        retriever_version="hybrid_v1",
        semantic_values={},
        evidence_bundle=bundle,
    )
    text, validated = finalize_grounded_answer("Nakit 9.999.999 TL.", pack, locale="tr")
    assert validated is False
    assert "doğrulanmamıştır" in text or "kanıt" in text.lower()


def test_rest_and_ws_share_finalize_invented_number_helper() -> None:
    """REST /chat/agent and WS stream both call the shared finalize helper."""
    from pathlib import Path

    app_dir = Path(__file__).resolve().parents[2] / "app" / "api"
    rest_src = (app_dir / "chat.py").read_text(encoding="utf-8")
    ws_src = (app_dir / "ws_stream.py").read_text(encoding="utf-8")
    assert "prepare_grounded_chat" in rest_src
    assert "finalize_grounded_answer" in rest_src
    assert "prepare_grounded_chat" in ws_src
    assert "finalize_grounded_answer" in ws_src

    bundle = EvidenceBundle(
        query="nakit",
        org_id="org-1",
        citations=[
            EvidenceCitation("j1", 0, "cfo_transactions_raw", 0.5, "unrelated memo"),
        ],
    )
    pack = GroundedChatPack(
        system_prompt="base",
        evidence_found=True,
        evidence_tx_count=1,
        evidence_semantic_count=0,
        retriever_version="hybrid_v1",
        semantic_values={},
        evidence_bundle=bundle,
    )
    text, validated = finalize_grounded_answer("Cash is 9.999.999 TL", pack, locale="tr")
    assert validated is False
    assert "doğrulanmamıştır" in text or "kanıt" in text.lower()
