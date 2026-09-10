"""Tests for platform engineering layer — contracts, conductor, verifier."""

from __future__ import annotations

from datetime import UTC

from app.agents.state import AgentRunConfig, CFOState
from app.agents.verifier_node import evaluate_cfo_state
from app.platform.conductor import ManagementConductor, signals_from_company_context
from app.platform.contracts import AgentRole, EvidenceBundle, EvidenceCitation
from app.platform.policies import CONFIDENCE_AUTO_PROCEED_MIN, ROLE_DEFAULT_DEPTH
from app.services.rag.retriever import HybridRagRetriever, get_rag_retriever


def test_role_default_depth_covers_management_roles() -> None:
    assert ROLE_DEFAULT_DEPTH["cfo"] >= 2
    assert ROLE_DEFAULT_DEPTH["ceo"] >= 2
    assert "chro" in ROLE_DEFAULT_DEPTH


def test_conductor_skips_roles_without_data_signals() -> None:
    conductor = ManagementConductor()
    plan = conductor.plan(
        org_id="org-1",
        trigger="upload_complete",
        available_signals={"cfo_result", "transactions"},
    )
    cfo = next(p for p in plan.roles if p.role == AgentRole.CFO)
    chro = next(p for p in plan.roles if p.role == AgentRole.CHRO)
    assert cfo.should_run is True
    assert chro.should_run is False


def test_conductor_force_role_overrides_missing_signals() -> None:
    conductor = ManagementConductor()
    plan = conductor.plan(
        org_id="org-1",
        trigger="manual",
        available_signals=set(),
        force_roles={AgentRole.CTO},
    )
    cto = next(p for p in plan.roles if p.role == AgentRole.CTO)
    assert cto.should_run is True
    assert cto.reason == "forced"


def test_signals_from_company_context() -> None:
    signals = signals_from_company_context(
        {"active_cfo_job_id": "j1", "last_cfo_result": {"revenue": 1}}
    )
    assert "cfo_result" in signals
    assert "transactions" in signals


def test_verifier_holds_on_low_confidence() -> None:
    state: CFOState = {
        "job_id": "j1",
        "file_path": "/tmp/x.csv",
        "file_type": "csv",
        "logs": [],
        "min_confidence": 0.5,
        "awaiting_review": False,
        "halted": False,
    }
    verdict = evaluate_cfo_state(state, run_config=AgentRunConfig(require_review=True))
    assert verdict.should_hold is True
    assert any("min_confidence" in r for r in verdict.reasons)


def test_verifier_proceeds_when_healthy() -> None:
    state: CFOState = {
        "job_id": "j1",
        "file_path": "/tmp/x.csv",
        "file_type": "csv",
        "logs": [],
        "min_confidence": 0.95,
        "awaiting_review": False,
        "halted": False,
        "reflection_scores": {
            "pnl": {"overall_score": 0.8},
            "cashflow": {"overall_score": 0.75},
        },
    }
    verdict = evaluate_cfo_state(state, run_config=AgentRunConfig(require_review=True))
    assert verdict.action == "proceed"


def test_verifier_halt_on_pipeline_halted() -> None:
    state: CFOState = {
        "job_id": "j1",
        "file_path": "/tmp/x.csv",
        "file_type": "csv",
        "logs": [],
        "min_confidence": 1.0,
        "halted": True,
        "error": "fatal",
    }
    verdict = evaluate_cfo_state(state)
    assert verdict.should_halt is True


def _base_state(**over) -> CFOState:
    s: CFOState = {
        "job_id": "j1",
        "file_path": "/tmp/x.csv",
        "file_type": "csv",
        "logs": [],
        "min_confidence": 1.0,
        "awaiting_review": False,
        "halted": False,
    }
    s.update(over)  # type: ignore[typeddict-item]
    return s


def test_low_confidence_hold_is_not_bypassable_by_require_review_false() -> None:
    """CLAUDE.md Law #10 — a low-confidence result always routes to a human."""
    state = _base_state(min_confidence=0.5)
    verdict = evaluate_cfo_state(
        state, run_config=AgentRunConfig(require_review=False)
    )
    assert verdict.action == "hold_for_review"


def test_skill_needs_review_hold_is_not_bypassable() -> None:
    state = _base_state(awaiting_review=True)
    verdict = evaluate_cfo_state(
        state, run_config=AgentRunConfig(require_review=False)
    )
    assert verdict.action == "hold_for_review"
    assert any("needs_review" in r for r in verdict.reasons)


def test_reflection_hold_band_is_not_bypassable() -> None:
    state = _base_state(reflection_scores={"pnl": {"overall_score": 0.40}})
    verdict = evaluate_cfo_state(
        state, run_config=AgentRunConfig(require_review=False)
    )
    assert verdict.action == "hold_for_review"


def test_effective_threshold_comes_from_run_config() -> None:
    """auto_proceed_min_confidence=0.0 is a valid 'accept anything' run."""
    state = _base_state(min_confidence=0.3)
    verdict = evaluate_cfo_state(
        state,
        run_config=AgentRunConfig(require_review=False, auto_proceed_min_confidence=0.0),
    )
    assert verdict.action == "proceed"


def test_soft_reflection_warning_is_bypassable_by_require_review_false() -> None:
    state = _base_state(reflection_scores={"pnl": {"overall_score": 0.65}})  # warn band
    held = evaluate_cfo_state(state, run_config=AgentRunConfig(require_review=True))
    assert held.action == "hold_for_review"
    proceeded = evaluate_cfo_state(
        state, run_config=AgentRunConfig(require_review=False)
    )
    assert proceeded.action == "proceed"


def test_evidence_bundle_prompt_block() -> None:
    bundle = EvidenceBundle(
        query="nakit akışı",
        org_id="org-1",
        citations=[
            EvidenceCitation(
                job_id="job-1",
                chunk_index=0,
                source_type="cfo_transactions_raw",
                score=0.42,
                preview="Office rent payment",
            )
        ],
    )
    block = bundle.to_prompt_block()
    assert "Office rent" in block
    assert bundle.found is True


def test_confidence_policy_matches_project_law() -> None:
    assert CONFIDENCE_AUTO_PROCEED_MIN == 0.80


def test_conductor_allows_helper() -> None:
    from app.agents.orchestration.auto_chain import _conductor_allows

    assert _conductor_allows("risk", {"risk", "audit"}, has_plan=True) is True
    assert _conductor_allows("ceo", set(), has_plan=True) is False
    assert _conductor_allows("ceo", set(), has_plan=False) is True


def test_default_rag_retriever_is_hybrid() -> None:
    assert isinstance(get_rag_retriever(), HybridRagRetriever)


def test_board_deck_pdf_smoke() -> None:
    from app.services.board_deck_pdf import BoardDeckPDFBuilder

    builder = BoardDeckPDFBuilder()
    pdf = builder.build_pdf(
        {
            "company_name": "Golden Path Inc",
            "period": "2026-08",
            "health_score": 78,
            "health_label": "healthy",
            "executive_summary": "Revenue stable; runway adequate.",
            "top_priorities": ["Extend runway", "Reduce CAC"],
            "insights": [
                {
                    "title": "Cash",
                    "severity": "medium",
                    "description": "Monitor burn rate weekly.",
                }
            ],
            "cfo_data": {"pnl": {"revenue": 1_000_000, "net_margin": 0.12}, "runway_months": 9},
            "swot": {
                "strengths": [{"text": "Strong team"}],
                "weaknesses": [],
                "opportunities": [],
                "threats": [],
            },
            "kri_posture": {
                "kri_score": 6.5,
                "counts": {"red": 1, "amber": 2, "green": 5},
                "red_kris": [],
            },
        }
    )
    assert isinstance(pdf, bytes)
    assert len(pdf) > 50
    if builder._has_reportlab:
        assert pdf.startswith(b"%PDF")


def test_canonical_fingerprint_stable() -> None:
    from datetime import datetime

    from app.services.data_plane.normalization_service import CanonicalTxRow
    from app.services.scheduled_sync import _canonical_fingerprint

    row = CanonicalTxRow(
        source_record_id="r1",
        transaction_date=datetime(2026, 1, 1, tzinfo=UTC),
        # Required rather than defaulted: a row that does not say where its
        # date came from is claiming a certainty nobody established.
        date_is_estimated=False,
        amount_cents=1000,
        currency="TRY",
        direction="expense",
        category=None,
        counterparty=None,
        description="x",
        confidence=80,
    )
    a = _canonical_fingerprint([row])
    b = _canonical_fingerprint([row])
    assert a == b
    assert len(a) == 32


def test_checkpoint_config_includes_thread_id() -> None:
    from app.agents.checkpointer import checkpoint_config, get_checkpointer

    cfg = checkpoint_config("job-abc", run_config={"require_review": True})
    assert cfg["configurable"]["thread_id"] == "job-abc"
    assert "run_config" in cfg["configurable"]
    # Must construct without raising (MemorySaver fallback OK)
    saver = get_checkpointer()
    assert saver is not None


def test_generic_coa_adapter_classifies_revenue() -> None:
    from app.services.regional.coa import GenericCoaAdapter, get_coa_adapter

    adapter = GenericCoaAdapter()
    result = adapter.classify(
        description="Acme subscription revenue",
        amount_cents=10000,
        transaction_type="income",
    )
    assert result.account_code == "4000"
    assert get_coa_adapter(regional_packs=[]).name == "generic_gaap"


def test_tax_rates_pack_aware() -> None:
    from app.services.regional.tax import tax_rates_for_org

    us = tax_rates_for_org(country_code="US", regional_packs=[])
    assert us["source"] == "generic"
    tr = tax_rates_for_org(country_code="US", regional_packs=["tr"])
    assert tr["pack"] == "tr"
    assert any(r["code"].startswith("kdv") for r in tr["rates"])


def test_coa_bridge_generic_and_tr() -> None:
    from app.services.regional.coa import CoaClassification
    from app.services.regional.coa_bridge import build_classifier_for_packs, coa_to_thp

    generic = build_classifier_for_packs([])
    result = generic.classify(
        description="Office rent payment",
        amount_kurus=50000,
        transaction_type="expense",
    )
    assert result.hesap_kodu
    assert result.confidence >= 0

    tr_clf = build_classifier_for_packs(["tr"])
    assert hasattr(tr_clf, "classify")
    assert type(tr_clf).__name__ == "THPClassifier"

    mapped = coa_to_thp(
        CoaClassification(
            account_code="4000",
            account_label="Revenue",
            confidence=0.9,
            method="rule",
            adapter="generic_gaap",
        )
    )
    assert mapped.hesap_kodu == "4000"
    assert mapped.tip == "gelir"


def test_locale_prompt_instruction() -> None:
    from app.services.regional.locale_prompt import (
        locale_language_instruction,
        with_locale_instruction,
    )

    assert "Turkish" in locale_language_instruction("tr-TR")
    assert "English" in locale_language_instruction("en-US")
    base = "You are the CFO agent."
    out = with_locale_instruction(base, "de-DE")
    assert "German" in out
    assert base in out
    # idempotent
    assert with_locale_instruction(out, "de-DE") == out


def test_build_conductor_plan_dict_shape() -> None:
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    async def _run() -> None:
        mock_ctx = MagicMock()
        mock_ctx.active_cfo_job_id = "j1"
        mock_ctx.last_cfo_result = {"pnl": {}}
        mock_ctx.last_risk_result = None
        mock_ctx.last_cto_result = None
        mock_ctx.last_cmo_result = None
        mock_ctx.last_chro_result = None
        mock_ctx.last_coo_result = None
        with patch(
            "app.services.company_context.get_company_context",
            new=AsyncMock(return_value=mock_ctx),
        ):
            from app.agents.orchestration.auto_chain import build_conductor_plan_dict

            plan = await build_conductor_plan_dict(org_id="org-1", agent="cfo")
        assert plan is not None
        assert plan["org_id"] == "org-1"
        assert plan["trigger"] == "cfo_complete"
        assert "roles" in plan

    asyncio.run(_run())
