"""Callers pass the arguments the pipelines actually take.

The auto-chain's risk and audit steps and the /agent-jobs audit and compliance
routes called their pipelines with parameter names the functions do not have
(job_id, risk_register_csv, audit_plan_csv, policies_csv, reporting_period)
and without required ones. Every call raised TypeError; the auto-chain logged
it as a warning and moved on, so the steps never ran and nothing failed.
Found by SonarCloud on the first PR analysis.

Each pipeline is replaced by a stand-in that binds the call against the real
function's signature — a mismatch fails here without running any agent.
"""
from __future__ import annotations

import inspect
from types import SimpleNamespace
from typing import Any

import pytest

import app.agents.audit.orchestrator as audit_orch
import app.agents.compliance.orchestrator as compliance_orch
import app.agents.orchestration.auto_chain as auto_chain
import app.agents.risk.orchestrator as risk_orch


def _strict_stand_in(real, calls: list[dict[str, Any]]):
    sig = inspect.signature(real)

    async def stand_in(*args, **kwargs):
        bound = sig.bind(*args, **kwargs)  # TypeError on any mismatch
        calls.append(dict(bound.arguments))
        return {}

    return stand_in


@pytest.fixture
def calls(monkeypatch):
    recorded: dict[str, list[dict[str, Any]]] = {"risk": [], "audit": [], "compliance": []}
    monkeypatch.setattr(risk_orch, "run_risk_pipeline",
                        _strict_stand_in(risk_orch.run_risk_pipeline, recorded["risk"]))
    monkeypatch.setattr(audit_orch, "run_audit_pipeline",
                        _strict_stand_in(audit_orch.run_audit_pipeline, recorded["audit"]))
    monkeypatch.setattr(compliance_orch, "run_compliance_pipeline",
                        _strict_stand_in(compliance_orch.run_compliance_pipeline, recorded["compliance"]))
    return recorded


@pytest.fixture
def no_context_io(monkeypatch):
    ctx = SimpleNamespace(update_agent_result=lambda *a, **k: None)

    async def get_ctx(org_id, db):
        return ctx

    async def save_ctx(c, db):
        return None

    async def no_consensus(**kwargs):
        return None

    monkeypatch.setattr(auto_chain, "get_company_context", get_ctx)
    monkeypatch.setattr(auto_chain, "save_company_context", save_ctx)
    monkeypatch.setattr(auto_chain, "_run_auto_consensus", no_consensus)


_CFO = {
    "pnl": {"revenue": 1_000_000, "net_profit": -50_000, "gross_margin_pct": 12.0},
    "alerts": [{"message": "Nakit açığı", "severity": "high"}],
    "anomalies": [{"description": "Mükerrer ödeme", "severity": "high"}],
}


async def test_auto_chain_risk_step_calls_the_pipeline(calls, no_context_io):
    ctx = SimpleNamespace(last_cfo_result=_CFO, company_name="Kobi A.Ş.")
    await auto_chain._run_risk_from_context("job-1", ctx, "org-1", db=None)
    assert len(calls["risk"]) == 1


async def test_auto_chain_audit_step_calls_the_pipeline(calls, no_context_io):
    ctx = SimpleNamespace(last_cfo_result=_CFO, company_name="Kobi A.Ş.")
    await auto_chain._run_audit_from_context("job-1", ctx, "org-1", db=None)
    assert len(calls["audit"]) == 1
    assert calls["audit"][0]["org_id"] == "org-1"


async def test_auto_chain_compliance_step_calls_the_pipeline(calls, no_context_io):
    ctx = SimpleNamespace(last_cfo_result=_CFO, company_name="Kobi A.Ş.")
    await auto_chain._run_compliance_from_context("job-1", ctx, "org-1", db=None)
    assert len(calls["compliance"]) == 1


async def test_agent_job_audit_maps_request_fields(calls):
    from app.api.agent_jobs import _dispatch_pipeline

    await _dispatch_pipeline("audit", "job-1", {
        "findings_csv": "f", "controls_csv": None, "audit_plan_csv": "plan",
        "company_name": "Kobi", "reporting_period": "2026-Q2",
    })
    got = calls["audit"][0]
    assert got["coverage_csv"] == "plan" and got["controls_csv"] == ""
    assert got["audit_period"] == "2026-Q2"


async def test_agent_job_compliance_maps_request_fields(calls):
    from app.api.agent_jobs import _dispatch_pipeline

    await _dispatch_pipeline("compliance", "job-1", {
        "policies_csv": "p", "violations_csv": None, "regulations_csv": "r",
        "company_name": "Kobi", "reporting_period": "2026-Q2",
    })
    got = calls["compliance"][0]
    assert got["job_id"] == "job-1" and got["policy_csv"] == "p"
    assert got["audit_period"] == "2026-Q2"


async def test_agent_job_risk_calls_the_pipeline(calls):
    from app.api.agent_jobs import _dispatch_pipeline

    await _dispatch_pipeline("risk", "job-1", {"register_csv": "r", "loss_csv": "l", "kri_csv": "k"})
    assert len(calls["risk"]) == 1
