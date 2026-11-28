"""Retention on a real PostgreSQL (the CI job "Migrations on Postgres"; the step fails if this is skipped).

What the KVKK inventory says must be what happens:

* with RETENTION_DRY_RUN ON, the always-enforced purges (`registry_stores.PURGES`: checkpoints past
  RETENTION_CHECKPOINT_DAYS, threads of an organisation that is gone or erased, erasure leftovers) DELETE, and the
  dry-run-by-default ones (notifications, alert history, outbox bodies, ...) only count, every row kept;
* with it OFF, everything due is deleted;
* nothing younger than its period is touched, and a run bound to one organisation reaches no other.

Skipped unless DATABASE_URL_OVERRIDE is a Postgres URL.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, TypedDict

import pytest
import pytest_asyncio
from langgraph.graph import END, StateGraph
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    func,
    insert,
    select,
    text,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401  (registers every table)
from app.agents import checkpointer as cp
from app.config import get_settings
from app.database import Base
from app.services import org_erasure
from app.services.outbox import SCRUBBED
from app.services.privacy import ephemeral, retention

URL = os.environ.get("DATABASE_URL_OVERRIDE", "")
T = Base.metadata.tables

pytestmark = [
    pytest.mark.skipif(not URL.startswith("postgresql"), reason="needs the CI Postgres service"),
    # The langgraph library stamps a checkpoint's `ts` with the wall clock and retention measures it so; the rows of
    # the other stores are dated from the same reading, so nothing here can flip at a date boundary.
    pytest.mark.real_clock(reason="checkpoint ts is wall-clock time, stamped by the langgraph library"),
]


class S(TypedDict, total=False):
    step: int


async def _one(state: S) -> S:
    return {"step": 1}


def _graph() -> Any:
    g = StateGraph(S)
    g.add_node("one", _one)
    g.set_entry_point("one")
    g.add_edge("one", END)
    return g.compile(checkpointer=cp.get_checkpointer())


@pytest.fixture(autouse=True)
def postgres_backend(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("LANGGRAPH_CHECKPOINT", "postgres")
    monkeypatch.setattr(get_settings(), "use_sqlite", False)
    monkeypatch.setattr(get_settings(), "storage_local_path", str(tmp_path))
    cp.reset_checkpointer()
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


def _fill(col: Any) -> Any:
    t = col.type
    if isinstance(t, JSON):
        return {}
    if isinstance(t, String | Text):
        return f"x{uuid.uuid4().hex}"[: (getattr(t, "length", None) or 40)]
    if isinstance(t, Boolean):
        return False
    if isinstance(t, Integer | Float):
        return 0
    if isinstance(t, DateTime):
        return datetime.now(UTC)
    raise AssertionError(f"cannot fill {col.table.name}.{col.name}")


async def put(db: AsyncSession, table_name: str, /, **fixed: Any) -> str:
    """One row: the given values, generated ones for the required columns without a default, NULL for the rest."""
    table = T[table_name]
    row = dict(fixed)
    for col in table.columns:
        if col.name in row or col.nullable or col.default is not None or col.server_default is not None:
            continue
        row[col.name] = _fill(col)
    pk = next(iter(table.primary_key.columns))
    if pk.name not in row:  # the model's own default when it has one (some ids are 32-character hex)
        row[pk.name] = pk.default.arg(None) if pk.default is not None and callable(pk.default.arg) else str(uuid.uuid4())
    await db.execute(insert(table).values(**row))
    return str(row[pk.name])


async def company(db: AsyncSession, now: datetime) -> str:
    """An active organisation with one old and one fresh row of each dry-run-by-default store."""
    org = await put(db, "organizations", name="Retention Test", slug=f"rt-{uuid.uuid4().hex[:10]}", is_active=True,
                    is_demo_guest=False)
    for age, tag in ((400, "old"), (2, "fresh")):
        when = now - timedelta(days=age)
        await put(db, "in_app_notifications", org_id=org, created_at=when, message=f"note {tag}")
        await put(db, "alert_history", org_id=org, created_at=when, message=f"alert {tag}")
        await put(db, "outbox_messages", org_id=org, status="sent", sent_at=when, created_at=when, body=f"body {tag}",
                  key=f"{org}-{tag}")
    return org


async def counts(db: AsyncSession, org: str, now: datetime) -> dict[str, int]:
    async def n(name: str, *where: Any) -> int:
        t = T[name]
        return int((await db.execute(select(func.count()).select_from(t).where(t.c.org_id == org, *where))).scalar_one())

    old = now - timedelta(days=300)
    ob = T["outbox_messages"]
    return {
        "old_notifications": await n("in_app_notifications", T["in_app_notifications"].c.created_at < old),
        "fresh_notifications": await n("in_app_notifications", T["in_app_notifications"].c.created_at >= old),
        "old_alerts": await n("alert_history", T["alert_history"].c.created_at < old),
        "fresh_alerts": await n("alert_history", T["alert_history"].c.created_at >= old),
        "old_bodies": await n("outbox_messages", ob.c.sent_at < old, ob.c.body != SCRUBBED),
        "fresh_bodies": await n("outbox_messages", ob.c.sent_at >= old, ob.c.body != SCRUBBED),
    }


async def threads(db: AsyncSession, needle: str) -> set[str]:
    found: set[str] = set()
    for table in cp.CHECKPOINT_DATA_TABLES:
        found |= set((await db.execute(
            text(f"SELECT DISTINCT thread_id FROM {table} WHERE strpos(thread_id, :n) > 0"), {"n": needle}
        )).scalars().all())
    return found


async def age_thread(db: AsyncSession, thread_id: str, days: int) -> None:
    """Move a thread's checkpoints `days` back on the WALL clock (what the library stamps and retention measures)."""
    from app.core.clock import wall_now

    ts = (wall_now() - timedelta(days=days)).isoformat()
    await db.execute(text("UPDATE checkpoints SET checkpoint = jsonb_set(checkpoint, '{ts}', to_jsonb(CAST(:ts AS text))) "
                          "WHERE thread_id = :t"), {"ts": ts, "t": thread_id})
    await db.commit()


FULL = {"old_notifications": 1, "fresh_notifications": 1, "old_alerts": 1, "fresh_alerts": 1, "old_bodies": 1,
        "fresh_bodies": 1}


async def test_dry_run_deletes_the_always_enforced_stores_and_only_counts_the_others(maker) -> None:
    now = datetime.now(UTC)
    gone_org = str(uuid.uuid4())  # an organisation id with no row: a deleted company
    async with maker() as db:
        a, b = await company(db, now), await company(db, now)
        await db.commit()
    app = _graph()
    old_a, fresh_a, old_b = (cp.checkpoint_config(str(uuid.uuid4()), org_id=o, run_id="r") for o in (a, a, b))
    for config in (old_a, fresh_a, old_b):
        await app.ainvoke({"step": 0}, config=config)
    orphan = cp.checkpoint_config(str(uuid.uuid4()), org_id=gone_org, run_id="r")
    await app.ainvoke({"step": 0}, config=orphan)
    tid = {k: c["configurable"]["thread_id"] for k, c in (("old_a", old_a), ("fresh_a", fresh_a), ("old_b", old_b),
                                                         ("orphan", orphan))}
    async with maker() as db:
        await age_thread(db, tid["old_a"], 10)
        await age_thread(db, tid["old_b"], 10)
        await age_thread(db, tid["fresh_a"], 1)  # younger than RETENTION_CHECKPOINT_DAYS (3)

    try:
        async with maker() as db:
            report = await retention.run_retention(db, dry_run=True, now=now)
        assert report["dry_run"] is True and report["status"] == "done"
        assert report["counts"]["checkpoints"] >= 2 and report["counts"]["checkpoints_orphaned"] >= 1
        assert report["counts"]["notifications"] >= 2 and report["actions"]["notifications"] == "counted"
        assert report["actions"]["checkpoints"] == "deleted" and report["actions"]["checkpoints_orphaned"] == "deleted"
        async with maker() as db:
            # enforced with dry-run ON: the old threads and the orphan are gone, the young thread stays
            assert await threads(db, tid["old_a"]) == set() and await threads(db, tid["old_b"]) == set()
            assert await threads(db, tid["orphan"]) == set(), "a deleted company's checkpoint survived"
            assert await threads(db, tid["fresh_a"]) == {tid["fresh_a"]}, "a checkpoint younger than its period went"
            # dry-run by default: counted, every row kept
            assert await counts(db, a, now) == FULL and await counts(db, b, now) == FULL

        # bound to one organisation, dry-run OFF: only A's due rows go
        async with maker() as db:
            await retention.run_retention(db, dry_run=False, org_id=a, now=now)
        async with maker() as db:
            assert await counts(db, a, now) == {**FULL, "old_notifications": 0, "old_alerts": 0, "old_bodies": 0}
            assert await counts(db, b, now) == FULL, "a run bound to one organisation reached another"

        # everything, dry-run OFF: every due row goes, nothing younger is touched
        async with maker() as db:
            off = await retention.run_retention(db, dry_run=False, now=now)
        assert off["actions"]["notifications"] == "deleted" and off["counts"]["notifications"] >= 1
        async with maker() as db:
            for org in (a, b):
                assert await counts(db, org, now) == {**FULL, "old_notifications": 0, "old_alerts": 0, "old_bodies": 0}
            assert await threads(db, tid["fresh_a"]) == {tid["fresh_a"]}
        async with maker() as db:  # the run rows carry counts only
            runs = (await db.execute(select(T["retention_runs"]).order_by(T["retention_runs"].c.finished_at.desc())
                                     .limit(3))).all()
            assert [r.dry_run for r in runs] == [False, False, True] and a not in repr([r.counts for r in runs])
    finally:
        async with maker() as db:
            await ephemeral._checkpoints_delete(db, a)
            await ephemeral._checkpoints_delete(db, b)
            await db.commit()


async def test_leftovers_of_an_erased_organisation_are_swept_with_dry_run_on_and_its_neighbour_is_untouched(
    maker, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A run in flight wrote through connections of its own after the erasure committed: a checkpoint thread, an agent
    memory episode, a model-call row and a run-ledger row. The retention run removes all of them for the erased
    company, whatever RETENTION_DRY_RUN says, and nothing of the company next door."""
    from app.services import agent_memory as am

    class _Store:  # the agent memory on PostgreSQL: the branch erasure and the sweep reach in the transaction
        _backend = am._PostgreSQLBackend("postgresql://unused")

    monkeypatch.setattr(am, "get_memory_store", lambda: _Store())
    now = datetime.now(UTC)
    async with maker() as db:
        await db.execute(text(am._PostgreSQLBackend._CREATE))
        erased, other = await company(db, now), await company(db, now)
        await db.commit()
    async with maker() as db:
        await org_erasure.erase_org(db, erased, storage_root=tmp_path)

    async def late_rows(db: AsyncSession, org: str) -> str:
        thread = f"{org}:{uuid.uuid4()}:late"
        # Raw rows, as a writer that raced the claim would have left them (the guarded saver refuses them now).
        await db.execute(text("INSERT INTO checkpoints (thread_id, checkpoint_ns, checkpoint_id, checkpoint, metadata) "
                              "VALUES (:t, '', :c, CAST(:ck AS jsonb), CAST('{}' AS jsonb))"),
                         {"t": thread, "c": str(uuid.uuid4()), "ck": json.dumps({"ts": now.isoformat()})})
        await db.execute(text("INSERT INTO agent_memory_episodes (id, org_id, agent, period, summary, narrative, created_at) "
                              "VALUES (:id, :o, 'pnl_agent', '2026-Q4', '{}', 'late narrative', 0)"),
                         {"id": str(uuid.uuid4()), "o": org})
        await put(db, "llm_call_logs", org_id=org, task_type="late", model="m", ok=True, created_at=now)
        await put(db, "agent_runs", org_id=org, pipeline="cfo", status="completed", attempt=1)
        return thread

    _ = _graph()  # the library's tables exist before raw rows are written
    async with maker() as db:
        t_erased, t_other = await late_rows(db, erased), await late_rows(db, other)
        await db.commit()

    async def left(db: AsyncSession, org: str) -> dict[str, int]:
        out = {"memory": int((await db.execute(text("SELECT count(*) FROM agent_memory_episodes WHERE org_id = :o"),
                                               {"o": org})).scalar_one())}
        for name in ("llm_call_logs", "agent_runs"):
            t = T[name]
            out[name] = int((await db.execute(select(func.count()).select_from(t).where(t.c.org_id == org))).scalar_one())
        return out

    try:
        async with maker() as db:
            report = await retention.run_retention(db, dry_run=True, now=now)
        assert report["dry_run"] is True and report["counts"]["erasure_leftovers"] >= 4
        async with maker() as db:
            assert await threads(db, t_erased) == set(), "a checkpoint written after the erasure survived"
            assert await left(db, erased) == {"memory": 0, "llm_call_logs": 0, "agent_runs": 0}
            assert await threads(db, t_other) == {t_other}
            assert await left(db, other) == {"memory": 1, "llm_call_logs": 1, "agent_runs": 1}
    finally:
        async with maker() as db:
            await db.execute(text("DELETE FROM agent_memory_episodes WHERE org_id IN (:a, :b)"), {"a": erased, "b": other})
            await ephemeral._checkpoints_delete(db, other)
            await db.commit()
