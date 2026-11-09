"""Plan v10 §14 G1 — what a role derives from the CFO result passes the same gate as the CFO result.

Risk, Audit, Compliance and CEO results were written straight into the company context by
the auto-chain (and by the CEO endpoint), while the same role run by hand was held for the
owner when its confidence was unmeasured. One role, two doors, and only one of them gated.

A result derived from the CFO's can claim no more than the CFO's own confidence: it
inherits it. A parent whose confidence is unknown makes the child's unknown, and an unknown
confidence is held (`platform.run_gate`: unknown is not calm). A confident parent writes,
and the written result carries the gate's decision.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.agents.orchestration import auto_chain
from app.models.agent_job import AgentJob, AgentJobStatus
from app.services.company_context import get_company_context, save_company_context
from tests.api_helpers import bellek_istemcisi, kullanici

APP = Path(__file__).resolve().parents[1] / "app"


@pytest_asyncio.fixture
async def ortam():
    async with bellek_istemcisi() as c:
        _, org_id, _ = await kullanici(c, "turetilmis@example.com")
        yield c, org_id


async def _context_with_cfo(client, org_id: str, confidence: float | None) -> Any:
    async with client._maker() as db:
        ctx = await get_company_context(org_id, db)
        ctx.update_agent_result("cfo", {"job_id": "J1", "dashboard": {}, "min_confidence": confidence})
        await save_company_context(ctx, db)


async def _stored(client, org_id: str, agent: str) -> dict | None:
    async with client._maker() as db:
        return getattr(await get_company_context(org_id, db), f"last_{agent}_result", None)


async def _held(client, org_id: str, agent: str) -> list[AgentJob]:
    async with client._maker() as db:
        return list((await db.execute(select(AgentJob).where(
            AgentJob.org_id == org_id, AgentJob.agent_type == agent,
            AgentJob.status == AgentJobStatus.AWAITING_REVIEW,
        ))).scalars().all())


async def _derive(client, org_id: str, agent: str, confidence: float | None) -> None:
    from app.services.context_persist import write_derived_result

    await _context_with_cfo(client, org_id, confidence)
    async with client._maker() as db:
        await write_derived_result(db, org_id, agent, {"summary": "x", "auto_generated": True},
                                   parent_agent="cfo", job_id="J1")


@pytest.mark.parametrize("agent", ["risk", "audit", "compliance", "ceo"])
async def test_a_confident_parent_lets_the_result_through_with_its_gate_record(ortam, agent):
    client, org_id = ortam
    await _derive(client, org_id, agent, 0.9)

    stored = await _stored(client, org_id, agent)
    assert stored is not None and stored["summary"] == "x"
    assert stored["gate"]["awaiting_review"] is False
    assert stored["gate"]["min_confidence"] == 0.9
    assert await _held(client, org_id, agent) == []


@pytest.mark.parametrize("agent", ["risk", "audit", "compliance", "ceo"])
async def test_an_unknown_parent_confidence_holds_the_result_for_the_owner(ortam, agent):
    client, org_id = ortam
    await _derive(client, org_id, agent, None)

    assert await _stored(client, org_id, agent) is None
    held = await _held(client, org_id, agent)
    assert len(held) == 1
    assert held[0].result_json["gate"]["awaiting_review"] is True


@pytest.mark.parametrize("agent", ["risk", "audit", "compliance", "ceo"])
async def test_a_low_confidence_parent_holds_the_result(ortam, agent):
    client, org_id = ortam
    await _derive(client, org_id, agent, 0.5)

    assert await _stored(client, org_id, agent) is None
    assert len(await _held(client, org_id, agent)) == 1


async def test_a_parent_that_never_ran_holds_the_result_too(ortam):
    from app.services.context_persist import write_derived_result

    client, org_id = ortam
    async with client._maker() as db:
        await write_derived_result(db, org_id, "risk", {"summary": "x"}, parent_agent="cfo", job_id="J1")
    assert await _stored(client, org_id, "risk") is None
    assert len(await _held(client, org_id, "risk")) == 1


async def test_the_auto_chained_risk_run_goes_through_the_gate(ortam, monkeypatch):
    client, org_id = ortam
    await _context_with_cfo(client, org_id, None)

    async def fake_pipeline(**kwargs):
        return {"risk_summary": {"level": "low"}}

    monkeypatch.setattr("app.agents.risk.orchestrator.run_risk_pipeline", fake_pipeline)
    monkeypatch.setattr(auto_chain, "_build_kri_csv_from_cfo", lambda cfo: "kri")
    monkeypatch.setattr(auto_chain, "_build_risk_csv_from_cfo", lambda cfo: "risk")
    monkeypatch.setattr(auto_chain, "_run_auto_consensus", _no_consensus)

    async with client._maker() as db:
        ctx = await get_company_context(org_id, db)
        await auto_chain._run_risk_from_context("J1", ctx, org_id, db)

    assert await _stored(client, org_id, "risk") is None
    assert len(await _held(client, org_id, "risk")) == 1


async def _no_consensus(**kwargs):
    return None


async def test_the_auto_chained_audit_and_compliance_runs_go_through_the_gate(ortam, monkeypatch):
    client, org_id = ortam
    await _context_with_cfo(client, org_id, None)

    async def fake_audit(**kwargs):
        return {"audit_summary": {"findings": 0}}

    async def fake_compliance(**kwargs):
        return {"compliance_summary": {"ok": True}}

    monkeypatch.setattr("app.agents.audit.orchestrator.run_audit_pipeline", fake_audit)
    monkeypatch.setattr("app.agents.compliance.orchestrator.run_compliance_pipeline", fake_compliance)
    monkeypatch.setattr(auto_chain, "_build_audit_findings_from_cfo", lambda cfo: "findings")

    async with client._maker() as db:
        ctx = await get_company_context(org_id, db)
        await auto_chain._run_audit_from_context("J1", ctx, org_id, db)
        await auto_chain._run_compliance_from_context("J1", ctx, org_id, db)

    for agent in ("audit", "compliance"):
        assert await _stored(client, org_id, agent) is None, agent
        assert len(await _held(client, org_id, agent)) == 1, agent


# What may write a role's result into the context directly, and why. Everything else goes
# through `write_derived_result` or `persist_agent_completion`.
DIRECT_WRITERS = {
    "services/company_context.py": "the method itself, and a thin service wrapper",
    "services/context_persist.py": "the gate",
    "post_completion.py": "the CFO view of an analysis that already passed the gate as a job",
    "services/scheduled_sync.py": "a connector overlay: commit counts read from an API, no model",
}


def test_no_other_code_writes_a_role_result_into_the_context_directly():
    """A ratchet: a new direct write is a new door around the gate."""
    pattern = re.compile(r"\.update_agent_result\(")
    found = {}
    for path in APP.rglob("*.py"):
        relative = path.relative_to(APP).as_posix()
        if pattern.search(path.read_text(encoding="utf-8", errors="ignore")):
            found[relative] = True
    unexpected = sorted(set(found) - set(DIRECT_WRITERS))
    assert unexpected == []
