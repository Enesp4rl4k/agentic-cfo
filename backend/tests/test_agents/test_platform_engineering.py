"""Tests for platform engineering layer — contracts, conductor, verifier."""

from __future__ import annotations

from app.agents.state import AgentRunConfig, CFOState
from app.agents.verifier_node import evaluate_cfo_state
from app.platform.conductor import ManagementConductor, signals_from_company_context
from app.platform.contracts import AgentRole, EvidenceBundle, EvidenceCitation
from app.platform.policies import CONFIDENCE_AUTO_PROCEED_MIN, ROLE_DEFAULT_DEPTH


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
