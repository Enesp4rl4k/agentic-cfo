"""Erasure against an analysis run in flight, on a real PostgreSQL (the CI job "Migrations on Postgres"; the step
fails if this is skipped).

A CFO run that finishes after its organisation's erasure committed must leave ZERO rows for that organisation
(`app/services/privacy/tombstone.py`):

* the checkpoint saver refuses every write once the erasure is claimed/committed: a run paused mid-graph while the
  erasure commits is resumed, and nothing of it is written;
* a results write that holds the organisation's lock in SHARED mode makes the erasure wait, and the erasure then
  deletes what it wrote; a results write after the erasure is refused;
* the run ledger writes nothing for an erased company; the agent memory insert is refused by its own condition;
* a claimed (`executing`) request is a tombstone, a `failed` one is not.

The interleavings are forced with events and a held lock, never with timing alone. Skipped unless
DATABASE_URL_OVERRIDE is a Postgres URL.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, TypedDict

import pytest
import pytest_asyncio
from langgraph.graph import END, StateGraph
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401  (registers every table)
from app.agents import checkpointer as cp
from app.config import get_settings
from app.database import Base
from app.models.erasure_record import OrgErasureRequest
from app.services import org_erasure
from app.services.privacy import ephemeral, tombstone
from app.services.privacy.tombstone import OrgErasedError, is_erased, refuse_if_erased
from tests.test_retention_postgres import put

URL = os.environ.get("DATABASE_URL_OVERRIDE", "")
T = Base.metadata.tables

pytestmark = pytest.mark.skipif(not URL.startswith("postgresql"), reason="needs the CI Postgres service")


class S(TypedDict, total=False):
    first: int
    second: int
    narrative: str


GATE: dict[str, asyncio.Event] = {}


async def step_one(state: S) -> S:
    return {"first": 1, "narrative": "Tedarikçi ZZREALNAME A.Ş. ödemesi"}  # restored text with a real name


async def step_two(state: S) -> S:
    GATE["started"].set()
    await GATE["release"].wait()  # the erasure commits while the run waits here
    return {"second": 2}


def build_app() -> Any:
    g = StateGraph(S)
    g.add_node("one", step_one)
    g.add_node("two", step_two)
    g.set_entry_point("one")
    g.add_edge("one", "two")
    g.add_edge("two", END)
    return g.compile(checkpointer=cp.get_checkpointer())


@pytest.fixture(autouse=True)
def postgres_backend(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("LANGGRAPH_CHECKPOINT", "postgres")
    monkeypatch.setattr(get_settings(), "use_sqlite", False)
    monkeypatch.setattr(get_settings(), "storage_local_path", str(tmp_path))
    cp.reset_checkpointer()
    GATE.clear()
    yield
    pool = getattr(cp._CHECKPOINTER, "conn", None)
    if pool is not None and hasattr(pool, "close"):
        pool.close()
    cp.reset_checkpointer()


@pytest_asyncio.fixture
async def maker():
    engine = create_async_engine(URL)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def company(db: AsyncSession) -> str:
    org = await put(db, "organizations", name="Race Test", slug=f"race-{uuid.uuid4().hex[:10]}", is_active=True,
                    is_demo_guest=False)
    await db.commit()
    return org


async def checkpoint_rows(db: AsyncSession, org: str) -> int:
    total = 0
    for table in cp.CHECKPOINT_DATA_TABLES:
        total += int((await db.execute(text(f"SELECT count(*) FROM {table} WHERE thread_id LIKE :p"),
                                       {"p": cp.thread_like(org)})).scalar_one())
    return total


async def wait_for(predicate: Any, what: str, seconds: float = 20.0) -> None:
    deadline = asyncio.get_running_loop().time() + seconds
    while not await predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"timed out waiting for {what}")
        await asyncio.sleep(0.05)


async def test_a_cfo_run_that_completes_after_the_erasure_commit_leaves_zero_checkpoint_rows(
    maker, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    refusals: list[str] = []
    real = tombstone.thread_refused

    def spy(pool: Any, thread_id: str) -> bool:
        refused = real(pool, thread_id)
        if refused:
            refusals.append(thread_id)
        return refused

    monkeypatch.setattr(tombstone, "thread_refused", spy)  # before the saver is built: it binds the function
    async with maker() as db:
        org, other = await company(db), await company(db)
    GATE["started"], GATE["release"] = asyncio.Event(), asyncio.Event()
    app = build_app()
    run = asyncio.create_task(app.ainvoke({}, config=cp.checkpoint_config(str(uuid.uuid4()), org_id=org, run_id="r")))
    neighbour_cfg = cp.checkpoint_config(str(uuid.uuid4()), org_id=other, run_id="r")
    try:
        await asyncio.wait_for(GATE["started"].wait(), 30)

        async def written() -> bool:  # the input checkpoint and step one's (the library saves them asynchronously)
            async with maker() as s:
                n = await s.execute(text("SELECT count(*) FROM checkpoints WHERE thread_id LIKE :p"),
                                    {"p": cp.thread_like(org)})
                return int(n.scalar_one()) >= 2

        await wait_for(written, "step one's checkpoint")  # the run has persisted state: the erasure must find it
        async with maker() as db:
            result = await org_erasure.erase_org(db, org, storage_root=tmp_path)
        assert result.counts["_ephemeral"]["checkpoints_deleted"] > 0
        async with maker() as db:
            assert await checkpoint_rows(db, org) == 0
        GATE["release"].set()  # the run continues after the erasure committed
        outcome = await asyncio.gather(run, return_exceptions=True)
        assert refusals, f"the saver wrote for an erased organisation (run outcome: {outcome!r})"
        async with maker() as db:
            assert await checkpoint_rows(db, org) == 0, "the run wrote checkpoints after its organisation was erased"
        # another company keeps working
        GATE["started"], GATE["release"] = asyncio.Event(), asyncio.Event()
        GATE["release"].set()
        await build_app().ainvoke({}, config=neighbour_cfg)
        async with maker() as db:
            assert await checkpoint_rows(db, other) > 0
    finally:
        GATE["release"].set()
        if not run.done():
            run.cancel()
        async with maker() as db:
            await ephemeral._checkpoints_delete(db, other)
            await ephemeral._checkpoints_delete(db, org)
            await db.commit()


async def test_a_results_write_holding_the_shared_lock_makes_the_erasure_wait_then_go_with_it(
    maker, tmp_path: Path
) -> None:
    async with maker() as db:
        org = await company(db)
    async with maker() as writer, maker() as eraser:
        await refuse_if_erased(writer, org)  # the outputs' transaction of a run: lock shared, no tombstone yet
        await put(writer, "in_app_notifications", org_id=org, message="result of a run in flight")
        await put(writer, "agent_runs", org_id=org, pipeline="cfo", status="completed", attempt=1)
        erasure = asyncio.create_task(org_erasure.erase_org(eraser, org, storage_root=tmp_path))
        await asyncio.sleep(1.0)
        assert not erasure.done(), "the erasure did not wait for a results write holding the organisation's lock"
        await writer.commit()  # the run commits its results; the erasure goes on and must take them
        await asyncio.wait_for(erasure, 60)
    async with maker() as db:
        for name in ("in_app_notifications", "agent_runs"):
            t = T[name]
            n = (await db.execute(select(func.count()).select_from(t).where(t.c.org_id == org))).scalar_one()
            assert n == 0, f"{name}: a result committed while the erasure waited survived it"
    async with maker() as late:
        with pytest.raises(OrgErasedError):
            await refuse_if_erased(late, org)  # a run finishing now writes nothing


async def test_a_claimed_request_is_a_tombstone_and_a_failed_one_is_not(maker) -> None:
    async with maker() as db:
        org = await company(db)
        now = datetime.now(UTC)
        req = OrgErasureRequest(id=str(uuid.uuid4()), target_org_id=org, org_hash=tombstone.org_hash(org), mode="anonymise",
                                requested_by_hash="b" * 64, requested_at=now, expires_at=now + timedelta(days=7),
                                status="failed", scope="org")
        db.add(req)
        await db.commit()
        try:
            assert await is_erased(db, org) is False  # rolled back whole: the company keeps working
            req.status = "executing"
            await db.commit()
            assert await is_erased(db, org) is True
            with pytest.raises(OrgErasedError):
                await refuse_if_erased(db, org)
            await db.rollback()
            assert await is_erased(db, str(uuid.uuid4())) is False  # another organisation is not affected
        finally:
            await db.delete(req)
            await db.commit()


async def test_the_run_ledger_and_the_agent_memory_write_nothing_for_an_erased_organisation(
    maker, tmp_path: Path
) -> None:
    from app.agents.run_ledger import agent_run
    from app.services import agent_memory as am

    async with maker() as db:
        await db.execute(text(am._PostgreSQLBackend._CREATE))
        await db.commit()
        org, other = await company(db), await company(db)
    async with maker() as db:
        async with agent_run(db, pipeline="cfo", org_id=org, job_id=None) as handle:  # the row is committed at start
            async with maker() as eraser:
                await org_erasure.erase_org(eraser, org, storage_root=tmp_path)  # erased while the run is in flight
            handle.node("narrative")
    async with maker() as db:
        t = T["agent_runs"]
        assert (await db.execute(select(func.count()).select_from(t).where(t.c.org_id == org))).scalar_one() == 0

    backend = am._PostgreSQLBackend(URL.replace("postgresql+asyncpg://", "postgresql://"))
    try:
        for target in (org, other):
            await backend._async_save(am.EpisodeRecord(org_id=target, agent="pnl_agent", period="2026-Q4",
                                                       summary={"k": 1}, narrative="ZZREALNAME late"))
        async with maker() as db:
            rows = dict((await db.execute(text(
                "SELECT org_id, count(*) FROM agent_memory_episodes WHERE org_id IN (:a, :b) GROUP BY org_id"),
                {"a": org, "b": other})).all())
        assert rows.get(org, 0) == 0 and rows.get(other) == 1
    finally:
        if backend._pool is not None:
            await backend._pool.close()
        async with maker() as db:
            await db.execute(text("DELETE FROM agent_memory_episodes WHERE org_id IN (:a, :b)"), {"a": org, "b": other})
            await db.commit()
