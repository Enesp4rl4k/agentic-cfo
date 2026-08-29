"""Durable run ledger (Faz 14) — bookkeeping, failure capture, resume."""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.main  # noqa: F401 — full model registration for create_all
from app.agents.run_ledger import agent_run, resume_run
from app.database import Base
from app.models.agent_run import AgentRun


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_agent_run_records_completion(db):
    async with agent_run(db, pipeline="tr_vertical", org_id="org-1", job_id="job-1") as h:
        h.node("cfo")
        h.node("accounting")
        h.node("done")

    row = (await db.execute(select(AgentRun))).scalar_one()
    assert row.status == "completed"
    assert row.node_history == ["cfo", "accounting", "done"]
    assert row.current_node == "done"
    assert row.latency_ms is not None
    assert row.finished_at is not None


@pytest.mark.asyncio
async def test_agent_run_records_failure_and_reraises(db):
    with pytest.raises(RuntimeError, match="boom"):
        async with agent_run(db, pipeline="cfo", org_id="org-1", job_id="job-x"):
            raise RuntimeError("boom")

    row = (await db.execute(select(AgentRun))).scalar_one()
    assert row.status == "failed"
    assert "boom" in row.error
    assert row.finished_at is not None


@pytest.mark.asyncio
async def test_caller_can_set_terminal_status(db):
    async with agent_run(db, pipeline="tr_vertical", org_id="o", job_id="j") as h:
        h.row.status = "awaiting_review"

    row = (await db.execute(select(AgentRun))).scalar_one()
    assert row.status == "awaiting_review"  # not overwritten with "completed"


@pytest.mark.asyncio
async def test_resume_run_increments_attempt(db):
    # a prior failed run
    async with agent_run(db, pipeline="tr_vertical", org_id="o", job_id="j"):
        pass
    row = (await db.execute(select(AgentRun))).scalar_one()
    row.status = "failed"
    await db.commit()
    run_id = row.id

    calls: list[int] = []

    async def _entry(**kw):
        calls.append(1)
        return {"stage": "done", "approval_required": False}

    resumed, result = await resume_run(db, run_id, _entry, job_id="j")
    assert calls == [1]
    assert resumed.attempt == 2
    assert resumed.status == "completed"
    assert result["stage"] == "done"


@pytest.mark.asyncio
async def test_resume_run_rejects_completed(db):
    async with agent_run(db, pipeline="cfo", org_id="o", job_id="j"):
        pass
    row = (await db.execute(select(AgentRun))).scalar_one()

    async def _entry(**kw):
        return {}

    with pytest.raises(ValueError, match="already completed"):
        await resume_run(db, row.id, _entry)


@pytest.mark.asyncio
async def test_resume_run_marks_awaiting_review(db):
    async with agent_run(db, pipeline="tr_vertical", org_id="o", job_id="j"):
        pass
    row = (await db.execute(select(AgentRun))).scalar_one()
    row.status = "failed"
    await db.commit()

    async def _entry(**kw):
        return {"stage": "done", "approval_required": True}

    resumed, _ = await resume_run(db, row.id, _entry, job_id="j")
    assert resumed.status == "awaiting_review"
