"""The LangGraph checkpointer on a real PostgreSQL (the CI job "Migrations on Postgres").

Skipped unless DATABASE_URL_OVERRIDE is a Postgres URL. Proves, against the real saver and tables:

* a run interrupted after its first step is resumed from the checkpoint by a REBUILT app object (a restart, or
  another process): the finished step does not run again;
* two organisations that happen to use the same job id never see each other's checkpoint (thread ids are
  namespaced by organisation), and organisation erasure deletes only the erased organisation's threads;
* retention deletes idle threads;
* two processes starting together may both run the library's `setup()` (advisory lock, idempotent).
"""
from __future__ import annotations

import os
import threading
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, TypedDict

import pytest
import pytest_asyncio
from langgraph.graph import END, StateGraph
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.agents import checkpointer as cp
from app.config import get_settings
from app.services.privacy import ephemeral

URL = os.environ.get("DATABASE_URL_OVERRIDE", "")

pytestmark = pytest.mark.skipif(not URL.startswith("postgresql"), reason="needs the CI Postgres service")


class S(TypedDict, total=False):
    first: int
    second: int
    secret: str


CALLS: dict[str, int] = {}
FAIL_SECOND = {"on": True}


async def step_one(state: S) -> S:
    CALLS["one"] = CALLS.get("one", 0) + 1
    return {"first": 1, "secret": state.get("secret", "")}


async def step_two(state: S) -> S:
    CALLS["two"] = CALLS.get("two", 0) + 1
    if FAIL_SECOND["on"]:
        raise RuntimeError("worker died")
    return {"second": 2}


def build_app() -> Any:
    """A freshly built graph over a freshly built saver: what a restarted process has."""
    g = StateGraph(S)
    g.add_node("one", step_one)
    g.add_node("two", step_two)
    g.set_entry_point("one")
    g.add_edge("one", "two")
    g.add_edge("two", END)
    return g.compile(checkpointer=cp.get_checkpointer())


@pytest.fixture(autouse=True)
def postgres_backend(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LANGGRAPH_CHECKPOINT", "postgres")
    monkeypatch.setattr(get_settings(), "use_sqlite", False)
    CALLS.clear()
    FAIL_SECOND["on"] = True
    cp.reset_checkpointer()
    yield
    cp.reset_checkpointer()


@pytest_asyncio.fixture
async def maker():
    engine = create_async_engine(URL)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def _rows(db: AsyncSession, table: str, org: str) -> int:
    return int(
        (await db.execute(text(f"SELECT count(*) FROM {table} WHERE thread_id LIKE :p"), {"p": cp.thread_like(org)}))
        .scalar_one()
    )


async def test_an_interrupted_run_resumes_from_the_checkpoint_in_a_rebuilt_app() -> None:
    org, job = str(uuid.uuid4()), str(uuid.uuid4())
    config = cp.checkpoint_config(job, org_id=org)

    with pytest.raises(RuntimeError, match="worker died"):
        await build_app().ainvoke({"secret": "kept"}, config=config)
    assert CALLS == {"one": 1, "two": 1}

    cp.reset_checkpointer()  # the process is gone; only the database remains
    FAIL_SECOND["on"] = False
    result = await build_app().ainvoke(None, config=config)

    assert result["first"] == 1 and result["second"] == 2 and result["secret"] == "kept"
    assert CALLS == {"one": 1, "two": 2}, "the finished step ran again: resume did not use the checkpoint"
    assert cp.checkpointer_status() == {"backend": "postgres", "durable": True, "error": None}


async def test_two_organisations_with_the_same_job_id_never_share_a_checkpoint(maker) -> None:
    a, b, job = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    FAIL_SECOND["on"] = False
    app = build_app()
    await app.ainvoke({"secret": "A-only"}, config=cp.checkpoint_config(job, org_id=a))
    await app.ainvoke({"secret": "B-only"}, config=cp.checkpoint_config(job, org_id=b))

    saver = cp.get_checkpointer()
    got_a = saver.get_tuple(cp.checkpoint_config(job, org_id=a))
    got_b = saver.get_tuple(cp.checkpoint_config(job, org_id=b))
    assert got_a.checkpoint["channel_values"]["secret"] == "A-only"
    assert got_b.checkpoint["channel_values"]["secret"] == "B-only"
    assert saver.get_tuple(cp.checkpoint_config(job, org_id=str(uuid.uuid4()))) is None  # a third organisation: nothing
    async with maker() as db:
        assert await _rows(db, "checkpoints", a) > 0 and await _rows(db, "checkpoints", b) > 0

    # erasure of A, inside the erase transaction, leaves B whole
    async with maker() as db:
        deleted = await ephemeral._checkpoints_delete(db, a)
        await db.commit()
    assert deleted > 0
    async with maker() as db:
        for table in cp.CHECKPOINT_DATA_TABLES:
            assert await _rows(db, table, a) == 0, f"{table} still holds the erased organisation's state"
        assert await _rows(db, "checkpoints", b) > 0 and await _rows(db, "checkpoint_blobs", b) > 0
    assert saver.get_tuple(cp.checkpoint_config(job, org_id=b)).checkpoint["channel_values"]["secret"] == "B-only"

    async with maker() as db:  # clean up B
        await ephemeral._checkpoints_delete(db, b)
        await db.commit()


async def test_erasure_requires_a_uuid_and_never_matches_by_pattern(maker) -> None:
    async with maker() as db:
        with pytest.raises(ephemeral.CheckpointDeleteError):
            await ephemeral._checkpoints_delete(db, "%")  # a wildcard must never reach the LIKE


async def test_retention_deletes_idle_threads_and_keeps_recent_ones(maker) -> None:
    org, job_old = str(uuid.uuid4()), str(uuid.uuid4())
    FAIL_SECOND["on"] = False
    await build_app().ainvoke({"secret": "x"}, config=cp.checkpoint_config(job_old, org_id=org))

    async with maker() as db:
        future = datetime.now(UTC) + timedelta(days=45)
        dry = await cp.purge_old_checkpoints(db, days=30, dry_run=True, now=future)
        assert dry >= 1 and await _rows(db, "checkpoints", org) > 0  # counted, not deleted
        today = await cp.purge_old_checkpoints(db, days=30, dry_run=False, now=datetime.now(UTC))
        assert await _rows(db, "checkpoints", org) > 0, f"a fresh thread was purged ({today} threads)"
        await cp.purge_old_checkpoints(db, days=30, dry_run=False, now=future)
        await db.commit()
    async with maker() as db:
        for table in cp.CHECKPOINT_DATA_TABLES:
            assert await _rows(db, table, org) == 0


def test_two_processes_starting_together_can_both_run_setup() -> None:
    errors: list[BaseException] = []

    def build() -> None:
        try:
            cp._postgres_saver(get_settings().database_url_sync)
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=build) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert errors == []
