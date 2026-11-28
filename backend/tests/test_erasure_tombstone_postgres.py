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


# ── #164 review B1: every write path, by the session itself (privacy.write_guard) ─────────────────────────────


async def _context_rows(db: AsyncSession, org: str) -> dict[str, int]:
    out = {}
    for name in ("company_context_snapshots", "company_semantic_snapshots"):
        t = T[name]
        out[name] = int((await db.execute(select(func.count()).select_from(t).where(t.c.org_id == org))).scalar_one())
    return out


async def _redis() -> Any:
    from app.core.redis_client import get_redis

    client = await get_redis()
    assert client is not None, "the CI job has a Redis service: the Redis half of this test must run"
    return client


async def test_a_view_written_after_the_erasure_committed_and_was_swept_leaves_zero_rows(
    maker, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reviewer's scenario: the continuation's unlocked check passed; while the company view was being computed
    (minutes, LLM calls) the erasure committed and its final sweep finished; THEN the view is written. Refused: no
    company context, no semantic snapshot, no Redis key, no auto-chain."""
    from app import post_completion
    from app.services import company_view
    from app.services.privacy.tombstone import sweep_erased_org

    async with maker() as db:
        org = await company(db)
    spawned: list[str] = []
    monkeypatch.setattr(post_completion, "spawn_auto_chain", lambda *a, **k: spawned.append("chain"))
    computed: list[str] = []

    def should_replace(current: Any, new: Any) -> tuple[bool, str]:
        computed.append("view")  # the view was computed for a company that was live when the check ran
        return True, "applied_by_test"

    monkeypatch.setattr(company_view, "should_replace", should_replace)
    # Deterministic order: the erasure commits and its final sweep finishes ...
    async with maker() as eraser:
        await org_erasure.erase_org(eraser, org, storage_root=tmp_path)
    async with maker() as sweeper:
        await sweep_erased_org(sweeper, org, storage_root=tmp_path)
    # ... THEN the write of the view that was computed before starts.
    chain = {"dashboard": {"period": "2026-11", "kpis": {"revenue": 1}}, "anomalies": []}
    async with maker() as db:
        applied = await post_completion.apply_company_view(str(uuid.uuid4()), org, chain, db, force=True)
    assert applied is False and computed == ["view"] and spawned == []
    async with maker() as db:
        assert await _context_rows(db, org) == {"company_context_snapshots": 0, "company_semantic_snapshots": 0}
    client = await _redis()
    assert await client.get(f"company_context:{org}") is None

    # Every writer of the context is refused, not only the continuation's explicit check (the session guard).
    from app.services.company_context import CompanyContext, save_company_context

    async with maker() as db:
        await save_company_context(CompanyContext(org_id=org), db)
    async with maker() as db:
        assert await _context_rows(db, org) == {"company_context_snapshots": 0, "company_semantic_snapshots": 0}
    assert await client.get(f"company_context:{org}") is None


async def test_a_write_that_got_past_the_guard_is_removed_by_the_next_retention_run_rows_and_redis(
    maker, tmp_path: Path
) -> None:
    from app.services.privacy import retention, write_guard

    async with maker() as db:
        org, other = await company(db), await company(db)
    async with maker() as db:
        await org_erasure.erase_org(db, org, storage_root=tmp_path)
    client = await _redis()
    async with maker() as db:
        with write_guard.exempt(db):  # a writer the guard did not see
            for target in (org, other):
                await put(db, "company_context_snapshots", org_id=target, context_json="{}")
                await put(db, "company_semantic_snapshots", org_id=target, period_key="2026-11")
            await db.commit()
    for target in (org, other):
        await client.set(f"company_context:{target}", "late", ex=600)
        await client.set(f"trend:{target}", "late", ex=600)
    try:
        async with maker() as db:
            report = await retention.run_retention(db, dry_run=True)
        assert report["counts"]["erasure_leftovers"] >= 4
        async with maker() as db:
            assert await _context_rows(db, org) == {"company_context_snapshots": 0, "company_semantic_snapshots": 0}
            assert await _context_rows(db, other) == {"company_context_snapshots": 1, "company_semantic_snapshots": 1}
        assert await client.get(f"company_context:{org}") is None and await client.get(f"trend:{org}") is None
        assert await client.get(f"company_context:{other}") is not None, "the sweep reached another company's keys"
    finally:
        await client.delete(f"company_context:{other}", f"trend:{other}")


async def test_a_long_writer_holding_the_shared_lock_through_the_session_guard_makes_the_erasure_wait(
    maker, tmp_path: Path
) -> None:
    """No explicit call: the session's own guard takes the shared lock at the first flush of the org's rows."""
    from app.models.in_app_notification import InAppNotification

    async with maker() as db:
        org = await company(db)
    async with maker() as writer, maker() as eraser:
        writer.add(InAppNotification(org_id=org, level="info", domain="cfo", message="a long run's result"))
        await writer.flush()  # write_guard: lock shared, tombstone read, then the INSERT
        erasure = asyncio.create_task(org_erasure.erase_org(eraser, org, storage_root=tmp_path))
        await asyncio.sleep(1.0)
        assert not erasure.done(), "the erasure did not wait for a writer the session guard locked"
        writer.add(InAppNotification(org_id=org, level="info", domain="cfo", message="more of it"))
        await writer.commit()
        await asyncio.wait_for(erasure, 60)
    async with maker() as db:
        t = T["in_app_notifications"]
        assert (await db.execute(select(func.count()).select_from(t).where(t.c.org_id == org))).scalar_one() == 0
        db.add(InAppNotification(org_id=org, level="info", domain="cfo", message="after"))
        with pytest.raises(OrgErasedError):
            await db.flush()


async def test_the_tombstone_costs_two_statements_per_organisation_per_transaction(maker) -> None:
    """Measured: the shared lock and the tombstone read run once per organisation per transaction, however many rows
    the transaction writes (the answer is cached on the transaction, which holds the lock)."""
    from sqlalchemy import event, update

    from app.models.in_app_notification import InAppNotification

    async with maker() as db:
        org = await company(db)
    seen: list[str] = []

    def record(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
        if "pg_advisory_xact_lock_shared" in statement:
            seen.append("lock")
        elif "org_erasure_records" in statement:
            seen.append("tombstone")

    async with maker() as db:
        engine = db.bind.sync_engine  # type: ignore[union-attr]
        event.listen(engine, "before_cursor_execute", record)
        try:
            for _ in range(2):  # two transactions, five inserts and an update each
                for i in range(5):
                    db.add(InAppNotification(org_id=org, level="info", domain="cfo", message=f"row {i}"))
                    await db.flush()
                t = T["in_app_notifications"]
                await db.execute(update(t).where(t.c.org_id == org).values(is_read=True))
                await db.commit()
        finally:
            event.remove(engine, "before_cursor_execute", record)
    assert seen == ["lock", "tombstone", "lock", "tombstone"], seen
