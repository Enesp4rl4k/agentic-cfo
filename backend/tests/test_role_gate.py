"""Plan v9 §K0 / §V6 S1 — one gate for every role; what it holds stays out of the context."""
from __future__ import annotations

from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select

import app.database as database
from app.agents.audit.state import AuditStepLog
from app.agents.ceo.state import CEOStepLog
from app.agents.chro.state import CHROStepLog
from app.agents.cmo.state import CMOStepLog
from app.agents.compliance.state import ComplianceStepLog
from app.agents.coo.state import COOStepLog
from app.agents.cto.state import CTOStepLog
from app.agents.risk.state import RiskStepLog
from app.models.agent_job import AgentJob, AgentJobStatus
from app.platform.run_gate import evaluate, step_results
from tests.api_helpers import arka_plan_bitsin, bellek_istemcisi, kullanici

_CONF_LOGS = [CEOStepLog, CMOStepLog, COOStepLog, CTOStepLog]
_NODE_LOGS = [CHROStepLog, RiskStepLog, AuditStepLog, ComplianceStepLog]


# ── contract ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("log", _CONF_LOGS)
def test_roles_that_measure_pass_above_the_threshold_and_wait_below_it(log):
    assert not evaluate({"logs": [log(step="a", ok=True, confidence=0.9)]}).awaiting_review
    low = evaluate({"logs": [log(step="a", ok=True, confidence=0.9), log(step="b", ok=True, confidence=0.6)]})
    assert low.awaiting_review
    assert low.min_confidence == 0.6


@pytest.mark.parametrize("log", _NODE_LOGS)
def test_roles_that_measure_nothing_wait_for_a_person(log):
    """They auto-proceeded on every run: law 10 calls that a bug."""
    decision = evaluate({"logs": [log(node="a", status="completed", message="ok")]})
    assert decision.awaiting_review
    assert decision.min_confidence is None
    assert "ölçülmedi" in decision.reasons[0]


@pytest.mark.parametrize("log", _NODE_LOGS)
def test_every_log_shape_reads_as_one_contract(log):
    steps = step_results({"logs": [
        log(node="a", status="started", message="başladı"),
        log(node="a", status="failed", message="bozuk dosya"),
    ]})
    assert [(s.step, s.ok, s.status, s.detail) for s in steps] == [("a", False, "failed", "bozuk dosya")]


def test_a_skipped_step_has_no_confidence_and_does_not_count():
    steps = [{"step": "a", "ok": True, "confidence": 0.9},
             {"step": "b", "ok": True, "status": "skipped", "confidence": 1.0}]
    decision = evaluate({"logs": steps})
    assert decision.steps[1].confidence is None
    assert not decision.awaiting_review


@pytest.mark.parametrize("result", [
    {"logs": [{"step": "a", "ok": False, "confidence": 0.95}]},
    {"logs": [{"step": "a", "ok": True, "confidence": 0.95, "needs_review": True}]},
    {"logs": [{"step": "a", "ok": True, "confidence": 0.95}], "awaiting_review": True},
    {"logs": [{"step": "a", "ok": True, "confidence": 0.95}], "error": "patladı"},
    {"logs": [{"step": "a", "ok": True, "confidence": 0.95}], "min_confidence": 0.5},
    {"logs": []},
])
def test_what_holds_a_run(result):
    assert evaluate(result).awaiting_review


def test_a_synthesis_is_no_surer_than_what_it_read():
    from app.platform.run_gate import inherited_confidence

    inputs = [None, {"min_confidence": 0.92}, {"gate": {"min_confidence": 0.7}}, {"gate": {"min_confidence": None}}]
    assert inherited_confidence(inputs) == 0.7
    assert inherited_confidence([None, {}]) == 1.0


# ── flow ──────────────────────────────────────────────────────────────────────


_TEMIZ: dict[str, Any] = {"cmo_summary": {"x": 1}, "logs": [{"step": "a", "ok": True, "confidence": 0.9}]}
_ZAYIF: dict[str, Any] = {"cmo_summary": {"x": 2}, "logs": [{"step": "a", "ok": True, "confidence": 0.5}]}


@pytest_asyncio.fixture
async def ortam(monkeypatch):
    async with bellek_istemcisi() as c:
        monkeypatch.setattr(database, "get_session_factory", lambda eng=None: c._maker)
        monkeypatch.setattr(database, "session_factory", lambda: c._maker)
        monkeypatch.setattr(database, "engine", lambda: None)
        zincir: list[str] = []

        async def hook(agent: str, org_id: str, result: Any, *a: Any, **kw: Any) -> None:
            zincir.append(agent)

        monkeypatch.setattr("app.agents.orchestration.auto_chain.on_agent_complete", hook)
        yield c, zincir
        await arka_plan_bitsin()


async def _context_result(client, org_id: str) -> Any:
    from app.services.company_context import get_company_context

    async with client._maker() as db:
        return (await get_company_context(org_id, db)).last_cmo_result


async def _persist(client, org_id: str, result: dict) -> dict:
    from app.agents.orchestration import auto_chain
    from app.services.context_persist import persist_agent_completion

    async with client._maker() as db:
        return await persist_agent_completion(
            org_id, "cmo", dict(result), db, auto_chain_hook=auto_chain.on_agent_complete,
        )


async def test_a_confident_result_reaches_the_context(ortam):
    client, _ = ortam
    _, org_id, _ = await kullanici(client, "temiz@example.com", role="owner")
    gate = await _persist(client, org_id, _TEMIZ)
    assert gate["awaiting_review"] is False
    assert (await _context_result(client, org_id))["cmo_summary"] == {"x": 1}


async def test_a_held_result_stays_out_of_the_context_and_joins_the_queue(ortam):
    client, zincir = ortam
    headers, org_id, _ = await kullanici(client, "tutulan@example.com", role="owner")
    gate = await _persist(client, org_id, _ZAYIF)

    assert gate["awaiting_review"] is True
    assert not await _context_result(client, org_id)
    assert zincir == []
    res = await client.get("/api/v1/agent-jobs/review-queue", headers=headers)
    assert res.status_code == 200, res.text
    queue = res.json()["data"]
    assert [j["id"] for j in queue] == [gate["agent_job_id"]]
    assert queue[0]["gate"]["reasons"]


async def test_the_owner_approves_and_only_then_the_context_and_chain_move(ortam):
    client, zincir = ortam
    headers, org_id, user_id = await kullanici(client, "patron@example.com", role="owner")
    gate = await _persist(client, org_id, _ZAYIF)

    res = await client.post(f"/api/v1/agent-jobs/{gate['agent_job_id']}/approve", headers=headers)
    assert res.status_code == 200, res.text
    assert (await _context_result(client, org_id))["cmo_summary"] == {"x": 2}
    await arka_plan_bitsin()
    assert zincir == ["cmo"]
    async with client._maker() as db:
        job = await db.get(AgentJob, gate["agent_job_id"])
        assert job.status == AgentJobStatus.COMPLETED
        assert job.result_json["review"]["approved_by"] == user_id

    again = await client.post(f"/api/v1/agent-jobs/{gate['agent_job_id']}/approve", headers=headers)
    assert again.status_code == 409


async def test_only_the_owner_of_this_company_can_approve(ortam):
    from app.models.user import User

    client, _ = ortam
    _, org_id, _ = await kullanici(client, "sahip@example.com", role="owner")
    gate = await _persist(client, org_id, _ZAYIF)
    url = f"/api/v1/agent-jobs/{gate['agent_job_id']}/approve"

    baska, _, _ = await kullanici(client, "baska@example.com", role="owner")
    assert (await client.post(url, headers=baska)).status_code == 404

    analist, _, analist_id = await kullanici(client, "analist@example.com", attach_org=False)
    async with client._maker() as db:
        (await db.get(User, analist_id)).org_id = org_id
        await db.commit()
    assert (await client.post(url, headers=analist)).status_code == 403
    assert not await _context_result(client, org_id)


async def test_a_rejected_result_never_reaches_the_context(ortam):
    client, zincir = ortam
    headers, org_id, _ = await kullanici(client, "ret@example.com", role="owner")
    gate = await _persist(client, org_id, _ZAYIF)
    res = await client.post(f"/api/v1/agent-jobs/{gate['agent_job_id']}/reject", headers=headers)
    assert res.status_code == 200, res.text
    assert not await _context_result(client, org_id)
    assert zincir == []
    async with client._maker() as db:
        jobs = (await db.execute(select(AgentJob))).scalars().all()
    assert [j.status for j in jobs] == [AgentJobStatus.FAILED]


async def test_an_agent_job_below_the_gate_waits(ortam, monkeypatch):
    from app.api import agent_jobs

    client, zincir = ortam
    _, org_id, _ = await kullanici(client, "is@example.com", role="owner")

    async def dispatch(agent_type: str, job_id: str, input_data: dict) -> dict:
        return dict(_ZAYIF)

    monkeypatch.setattr(agent_jobs, "_dispatch_pipeline", dispatch)
    async with client._maker() as db:
        job = AgentJob(agent_type="cmo", org_id=org_id, status=AgentJobStatus.PENDING, input_data={})
        db.add(job)
        await db.commit()
        job_id = job.id

    await agent_jobs._run_agent_pipeline(job_id, "cmo", {})

    async with client._maker() as db:
        row = await db.get(AgentJob, job_id)
        assert row.status == AgentJobStatus.AWAITING_REVIEW
        assert row.result_json["gate"]["awaiting_review"] is True
        n = len((await db.execute(select(AgentJob))).scalars().all())
    assert n == 1                                   # no second queue row
    assert not await _context_result(client, org_id)
    assert zincir == []
