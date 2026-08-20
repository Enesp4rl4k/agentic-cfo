"""Tests for platform engineering layer — contracts, conductor, verifier."""

from __future__ import annotations

from app.agents.state import AgentRunConfig, CFOState
from app.agents.verifier_node import evaluate_cfo_state
from app.platform.conductor import ManagementConductor, signals_from_company_context
from app.platform.contracts import AgentRole, EvidenceBundle, EvidenceCitation
from app.platform.policies import CONFIDENCE_AUTO_PROCEED_MIN, ROLE_DEFAULT_DEPTH
from app.services.rag.retriever import EmbeddingRagRetriever, get_rag_retriever


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


def test_default_rag_retriever_is_embedding_capable() -> None:
    assert isinstance(get_rag_retriever(), EmbeddingRagRetriever)


def test_canonical_fingerprint_stable() -> None:
    from datetime import datetime, timezone
    from app.services.data_plane.normalization_service import CanonicalTxRow
    from app.services.scheduled_sync import _canonical_fingerprint

    row = CanonicalTxRow(
        source_record_id="r1",
        transaction_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
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
            from app.services.auto_chain import build_conductor_plan_dict

            plan = await build_conductor_plan_dict(org_id="org-1", agent="cfo")
        assert plan is not None
        assert plan["org_id"] == "org-1"
        assert plan["trigger"] == "cfo_complete"
        assert "roles" in plan

    asyncio.run(_run())
