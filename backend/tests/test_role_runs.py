"""Plan v9 §K0 / §V6 S2 — every role run leaves a durable record; a dead one is noticed."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest_asyncio
from sqlalchemy import select

import app.database as database
from app.models.agent_job import AgentJob, AgentJobStatus
from app.models.agent_run import AgentRun
from tests.api_helpers import arka_plan_bitsin, bellek_istemcisi, kullanici

_TEMIZ: dict[str, Any] = {"cmo_summary": {"x": 1}, "logs": [{"step": "a", "ok": True, "confidence": 0.9}]}
_ZAYIF: dict[str, Any] = {"cmo_summary": {"x": 2}, "logs": [{"step": "a", "ok": True, "confidence": 0.5}]}


@pytest_asyncio.fixture
async def client(monkeypatch):
    async with bellek_istemcisi() as c:
        monkeypatch.setattr(database, "get_session_factory", lambda eng=None: c._maker)
        monkeypatch.setattr(database, "session_factory", lambda: c._maker)
        monkeypatch.setattr(database, "engine", lambda: None)
        yield c
        await arka_plan_bitsin()


async def _job(client, org_id: str, status: str = AgentJobStatus.PENDING, **kw: Any) -> str:
    async with client._maker() as db:
        job = AgentJob(agent_type="cmo", org_id=org_id, status=status, input_data={}, **kw)
        db.add(job)
        await db.commit()
        return job.id


async def _runs(client, pipeline: str) -> list[AgentRun]:
    async with client._maker() as db:
        return list((await db.execute(select(AgentRun).where(AgentRun.pipeline == pipeline))).scalars())


async def _status(client, job_id: str) -> str:
    async with client._maker() as db:
        return (await db.get(AgentJob, job_id)).status


def _dispatching(monkeypatch, result: dict) -> list[str]:
    from app.api import agent_jobs

    calls: list[str] = []

    async def dispatch(agent_type: str, job_id: str, input_data: dict) -> dict:
        calls.append(job_id)
        return dict(result)

    monkeypatch.setattr(agent_jobs, "_dispatch_pipeline", dispatch)
    return calls


# ── AgentRun ──────────────────────────────────────────────────────────────────


async def test_an_agent_job_leaves_one_run_with_its_outcome(client, monkeypatch):
    from app.api.agent_jobs import _run_agent_pipeline

    _dispatching(monkeypatch, _TEMIZ)
    _, org_id, _ = await kullanici(client, "kayit@example.com", role="owner")
    job_id = await _job(client, org_id)
    await _run_agent_pipeline(job_id, "cmo", {})

    runs = await _runs(client, "cmo")
    assert [(r.status, r.job_id, r.org_id) for r in runs] == [("completed", job_id, org_id)]
    assert runs[0].finished_at is not None


async def test_a_held_job_is_awaiting_review_in_the_ledger_too(client, monkeypatch):
    from app.api.agent_jobs import _run_agent_pipeline

    _dispatching(monkeypatch, _ZAYIF)
    _, org_id, _ = await kullanici(client, "bekle@example.com", role="owner")
    await _run_agent_pipeline(await _job(client, org_id), "cmo", {})
    assert [r.status for r in await _runs(client, "cmo")] == ["awaiting_review"]


async def test_a_crashing_pipeline_is_failed_in_both_records(client, monkeypatch):
    from app.api import agent_jobs

    async def patladi(*a: Any) -> dict:
        raise RuntimeError("bozuk")

    monkeypatch.setattr(agent_jobs, "_dispatch_pipeline", patladi)
    _, org_id, _ = await kullanici(client, "cokus@example.com", role="owner")
    job_id = await _job(client, org_id)
    await agent_jobs._run_agent_pipeline(job_id, "cmo", {})

    assert await _status(client, job_id) == AgentJobStatus.FAILED
    assert [r.status for r in await _runs(client, "cmo")] == ["failed"]


async def test_the_cfo_worker_leaves_a_run(client, monkeypatch):
    from app.models.analysis_job import AnalysisJob, JobStatus
    from app.worker import run_cfo_analysis

    _, org_id, _ = await kullanici(client, "cfo@example.com", role="owner")
    async with client._maker() as db:
        job = AnalysisJob(filename="x.csv", file_path="/x.csv", file_type="csv", org_id=org_id,
                          status=JobStatus.PENDING)
        db.add(job)
        await db.commit()
        job_id = job.id

    async def sahte(**kw: Any) -> dict:
        return {"transactions": [], "dashboard_json": {"pnl": {"revenue": 0}}, "anomalies": [], "logs": [],
                "awaiting_review": False, "min_confidence": 0.95}

    monkeypatch.setattr("app.agents.orchestrator.run_cfo_pipeline", sahte)
    assert (await run_cfo_analysis({}, job_id)).get("ok") is True

    assert [(r.status, r.job_id) for r in await _runs(client, "cfo")] == [("completed", job_id)]


async def test_a_duplicate_delivery_is_not_a_run(client, monkeypatch):
    from app.models.analysis_job import AnalysisJob, JobStatus
    from app.worker import run_cfo_analysis

    _, org_id, _ = await kullanici(client, "cift@example.com", role="owner")
    async with client._maker() as db:
        job = AnalysisJob(filename="x.csv", file_path="/x.csv", file_type="csv", org_id=org_id,
                          status=JobStatus.COMPLETED)
        db.add(job)
        await db.commit()
        job_id = job.id

    assert (await run_cfo_analysis({}, job_id)).get("skipped") is True
    assert await _runs(client, "cfo") == []


_AUDIT_BODY = {
    "findings_csv": "finding_id,title,severity,status,area,owner,opened_date,due_date,closed_date\n"
                    "F1,Yetki,high,open,IT,Ali,2024-01-01,2024-02-01,\n",
    "controls_csv": "control_id,name,area,effectiveness,last_tested\nC1,Erisim,IT,effective,2024-01-01\n",
    "coverage_csv": "area,risk_rating,last_audit_date,planned\nIT,high,2024-01-01,true\n",
}


async def test_an_audit_run_is_recorded_and_held_not_lost(client):
    """Audit results never reached the company context by this path at all."""
    headers, _, _ = await kullanici(client, "denetim@example.com", role="owner")
    res = await client.post("/api/v1/audit/analyze", headers=headers, json=_AUDIT_BODY)
    assert res.status_code == 200, res.text
    assert res.json()["inceleme"]["awaiting_review"] is True

    assert [r.status for r in await _runs(client, "audit")] == ["awaiting_review"]
    queue = (await client.get("/api/v1/agent-jobs/review-queue", headers=headers)).json()["data"]
    assert [j["agent_type"] for j in queue] == ["audit"]

    approved = await client.post(f"/api/v1/agent-jobs/{queue[0]['id']}/approve", headers=headers)
    assert approved.status_code == 200, approved.text
    context = await client.get("/api/v1/context/me", headers=headers)
    assert context.status_code == 200, context.text


async def test_a_run_waiting_for_a_person_does_not_lower_the_success_rate(client):
    headers, org_id, _ = await kullanici(client, "slo@example.com", role="owner")
    async with client._maker() as db:
        for status in ("completed", "completed", "failed", "awaiting_review"):
            db.add(AgentRun(org_id=org_id, pipeline="chro", status=status))
        await db.commit()

    res = await client.get("/api/v1/runs/slo?days=7", headers=headers)
    assert res.status_code == 200, res.text
    assert "0.667" in res.text


# ── claim and lease ───────────────────────────────────────────────────────────


async def test_a_job_runs_once_however_often_it_is_delivered(client, monkeypatch):
    from app.api.agent_jobs import _run_agent_pipeline

    calls = _dispatching(monkeypatch, _TEMIZ)
    _, org_id, _ = await kullanici(client, "tek@example.com", role="owner")
    job_id = await _job(client, org_id)
    await _run_agent_pipeline(job_id, "cmo", {})
    await _run_agent_pipeline(job_id, "cmo", {})
    assert calls == [job_id]


async def test_the_reaper_fails_a_dead_run_and_leaves_a_human_gate_alone(client):
    from app.services.job_reaper import reap_stuck_jobs

    _, org_id, _ = await kullanici(client, "olu@example.com", role="owner")
    gecmis = datetime.now(UTC) - timedelta(hours=1)
    gelecek = datetime.now(UTC) + timedelta(hours=1)
    olu = await _job(client, org_id, AgentJobStatus.RUNNING, lease_expires_at=gecmis)
    canli = await _job(client, org_id, AgentJobStatus.RUNNING, lease_expires_at=gelecek)
    bekleyen = await _job(client, org_id, AgentJobStatus.AWAITING_REVIEW)
    kayip = await _job(client, org_id, AgentJobStatus.PENDING, created_at=gecmis)

    async with client._maker() as db:
        counts = await reap_stuck_jobs(db)

    assert counts["expired_agent_jobs"] == 2
    assert await _status(client, olu) == AgentJobStatus.FAILED
    assert await _status(client, kayip) == AgentJobStatus.FAILED
    assert await _status(client, canli) == AgentJobStatus.RUNNING
    assert await _status(client, bekleyen) == AgentJobStatus.AWAITING_REVIEW
