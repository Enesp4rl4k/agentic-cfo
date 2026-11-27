"""The LangGraph checkpointer on a real PostgreSQL (the CI job "Migrations on Postgres").

Skipped unless DATABASE_URL_OVERRIDE is a Postgres URL (the CI step fails if it is skipped). Proves, against the real
saver and tables:

* the saver can resume a thread in a REBUILT app object (a restart, or another process); production does not use
  this (every run has its own thread), but it shows the rows are durable;
* two organisations that happen to use the same job id never see each other's checkpoint (thread ids are
  namespaced by organisation), and organisation erasure deletes only the erased organisation's threads;
* the CEO path (`run_ceo_pipeline` with a CFO file, what `/ceo/analyze-from-job` calls) writes only rows namespaced
  by the job's organisation, and that organisation's erasure leaves none;
* un-namespaced rows written before the fix are removed by the organisation's erasure (its jobs) and by retention;
* a run without an organisation writes nothing; two runs on one job write two threads;
* deserialisation is strict: only the app's state types are rebuilt from a row;
* retention deletes idle threads;
* two processes starting together may both run the library's `setup()` (advisory lock, idempotent).
"""
from __future__ import annotations

import os
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, TypedDict

import pytest
import pytest_asyncio
from langgraph.graph import END, StateGraph
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.agents import checkpointer as cp
from app.agents.state import StepLog
from app.config import get_settings
from app.services.privacy import ephemeral

URL = os.environ.get("DATABASE_URL_OVERRIDE", "")

pytestmark = pytest.mark.skipif(not URL.startswith("postgresql"), reason="needs the CI Postgres service")

CSV = """\
date,description,amount,type,category
2024-01-05,Office Rent,-8000,expense,rent
2024-01-10,Client Payment A,25000,income,sales
2024-01-15,Electricity,-1500,expense,utilities
2024-01-20,Client Payment B,18000,income,sales
2024-01-25,Salaries,-30000,expense,payroll
"""


class S(TypedDict, total=False):
    first: int
    second: int
    secret: str
    log: Any
    gadget: Any


@dataclass
class Gadget:
    """A type the checkpoint allowlist does not name: a row must not rebuild it."""

    name: str


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


def _close(saver: Any) -> None:
    pool = getattr(saver, "conn", None)
    if pool is not None and hasattr(pool, "close"):
        pool.close()


@pytest.fixture(autouse=True)
def postgres_backend(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LANGGRAPH_CHECKPOINT", "postgres")
    monkeypatch.setattr(get_settings(), "use_sqlite", False)
    CALLS.clear()
    FAIL_SECOND["on"] = True
    cp.reset_checkpointer()
    yield
    _close(cp._CHECKPOINTER)
    cp.reset_checkpointer()


@pytest_asyncio.fixture
async def maker():
    engine = create_async_engine(URL)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
def cfo_on_postgres(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """The real CFO graph over the Postgres saver (the module compiled it at import over the test default), and a
    statement file. The organisation's stored base currency is not what is under test: no database lookup for it."""
    from app.agents import orchestrator

    monkeypatch.setattr(orchestrator, "cfo_graph", orchestrator.build_cfo_graph().compile(
        checkpointer=cp.get_checkpointer()))

    async def _no_base(org_id: Any) -> None:
        return None

    monkeypatch.setattr(orchestrator, "_stored_base_currency", _no_base)
    f = tmp_path / "statement.csv"
    f.write_text(CSV, encoding="utf-8")
    return str(f)


async def _rows(db: AsyncSession, table: str, org: str) -> int:
    return int(
        (await db.execute(text(f"SELECT count(*) FROM {table} WHERE thread_id LIKE :p"), {"p": cp.thread_like(org)}))
        .scalar_one()
    )


async def _threads_naming(db: AsyncSession, needle: str) -> set[str]:
    """Every thread id in any checkpoint table that contains `needle` (a job id): wherever it was written."""
    found: set[str] = set()
    for table in cp.CHECKPOINT_DATA_TABLES:
        found |= set((await db.execute(
            text(f"SELECT DISTINCT thread_id FROM {table} WHERE strpos(thread_id, :n) > 0"), {"n": needle}
        )).scalars().all())
    return found


async def test_a_thread_resumes_from_the_checkpoint_in_a_rebuilt_app() -> None:
    org, job = str(uuid.uuid4()), str(uuid.uuid4())
    config = cp.checkpoint_config(job, org_id=org, run_id="r1")

    with pytest.raises(RuntimeError, match="worker died"):
        await build_app().ainvoke({"secret": "kept"}, config=config)
    assert CALLS == {"one": 1, "two": 1}

    _close(cp._CHECKPOINTER)
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
    await app.ainvoke({"secret": "A-only"}, config=cp.checkpoint_config(job, org_id=a, run_id="r"))
    await app.ainvoke({"secret": "B-only"}, config=cp.checkpoint_config(job, org_id=b, run_id="r"))

    saver = cp.get_checkpointer()
    got_a = saver.get_tuple(cp.checkpoint_config(job, org_id=a, run_id="r"))
    got_b = saver.get_tuple(cp.checkpoint_config(job, org_id=b, run_id="r"))
    assert got_a.checkpoint["channel_values"]["secret"] == "A-only"
    assert got_b.checkpoint["channel_values"]["secret"] == "B-only"
    third = cp.checkpoint_config(job, org_id=str(uuid.uuid4()), run_id="r")
    assert saver.get_tuple(third) is None  # a third organisation: nothing
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
    got_b = saver.get_tuple(cp.checkpoint_config(job, org_id=b, run_id="r"))
    assert got_b.checkpoint["channel_values"]["secret"] == "B-only"

    async with maker() as db:  # clean up B
        await ephemeral._checkpoints_delete(db, b)
        await db.commit()


async def test_erasure_requires_a_uuid_and_never_matches_by_pattern(maker) -> None:
    async with maker() as db:
        with pytest.raises(ephemeral.CheckpointDeleteError):
            await ephemeral._checkpoints_delete(db, "%")  # a wildcard must never reach the LIKE
        with pytest.raises(ephemeral.CheckpointDeleteError):
            await ephemeral._checkpoints_delete(db, str(uuid.uuid4()), ["%"])  # nor through a job id


async def test_the_ceo_path_writes_only_org_namespaced_rows_and_erasure_leaves_none(maker, cfo_on_postgres) -> None:
    """B1: `/ceo/analyze-from-job` -> run_ceo_pipeline -> run_cfo_pipeline wrote the statement under `<job>-ceo-cfo`."""
    from app.agents.ceo.orchestrator import run_ceo_pipeline

    org, other, job = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    result = await run_ceo_pipeline(
        job_id=f"{job}-ceo", cfo_file_path=cfo_on_postgres, cfo_file_type="csv", org_id=org,
    )
    assert result.get("financial_summary"), "the CFO sub-pipeline did not run"
    # Another organisation's run, so the erasure below has something it must leave alone.
    await run_ceo_pipeline(job_id=f"{job}-ceo", cfo_file_path=cfo_on_postgres, cfo_file_type="csv", org_id=other)

    async with maker() as db:
        threads = await _threads_naming(db, job)
        assert threads, "the CFO run wrote no checkpoint at all"
        assert all(t.startswith((f"{org}:{job}-ceo-cfo:", f"{other}:{job}-ceo-cfo:")) for t in threads), threads
        assert await _rows(db, "checkpoints", org) > 0 and await _rows(db, "checkpoint_blobs", org) > 0

    async with maker() as db:
        counts = await ephemeral.erase_org_in_transaction(db, org, [job])
        await db.commit()
    assert counts["checkpoints_deleted"] > 0
    async with maker() as db:
        left = await _threads_naming(db, job)
        assert not [t for t in left if not t.startswith(f"{other}:")], f"the erased organisation still has {left}"
        for table in cp.CHECKPOINT_DATA_TABLES:
            assert await _rows(db, table, org) == 0, table
        assert await _rows(db, "checkpoints", other) > 0, "erasure reached another organisation"
        await ephemeral._checkpoints_delete(db, other)
        await db.commit()


async def test_a_run_without_an_organisation_writes_nothing(maker, cfo_on_postgres) -> None:
    from app.agents.orchestrator import run_cfo_pipeline

    job = str(uuid.uuid4())
    result = await run_cfo_pipeline(job_id=job, file_path=cfo_on_postgres, file_type="csv", org_id=None)
    assert result.get("pnl"), "the pipeline did not run"
    async with maker() as db:
        assert await _threads_naming(db, job) == set()


async def test_two_runs_on_one_job_write_two_threads(maker, cfo_on_postgres) -> None:
    """M1: the tr-vertical side run used the worker's thread; channel values crossed runs and processes."""
    from app.agents.orchestrator import run_cfo_pipeline

    org, job = str(uuid.uuid4()), str(uuid.uuid4())
    await run_cfo_pipeline(job_id=job, file_path=cfo_on_postgres, file_type="csv", org_id=org,
                           budget_input={"revenue": 1})
    await run_cfo_pipeline(job_id=job, file_path=cfo_on_postgres, file_type="csv", org_id=org)
    async with maker() as db:
        threads = await _threads_naming(db, job)
        assert len(threads) == 2 and all(t.startswith(f"{org}:{job}:") for t in threads), threads
        await ephemeral._checkpoints_delete(db, org)
        await db.commit()


async def test_legacy_unnamespaced_rows_go_with_the_erasure_and_with_retention(maker) -> None:
    """Rows the branch wrote before the fix: `<job>-ceo-cfo` (no organisation) and `-:<job>` (empty organisation)."""
    org, job, stranger = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    FAIL_SECOND["on"] = False
    app = build_app()
    for tid in (f"{job}-ceo-cfo", f"-:{job}", f"{stranger}-ceo-cfo"):  # a thread id by hand: the pre-fix shape
        await app.ainvoke({"secret": "legacy"}, config={"configurable": {"thread_id": tid}})

    async with maker() as db:
        await ephemeral.erase_org_in_transaction(db, org, [job])
        await db.commit()
    async with maker() as db:
        assert await _threads_naming(db, job) == set(), "a legacy row of the erased organisation's job survived"
        assert await _threads_naming(db, stranger) == {f"{stranger}-ceo-cfo"}, "erasure reached another job"

    # Retention: the orphan goes at once, whatever its age and even with checkpoint_days = 0; namespaced rows stay.
    kept = cp.checkpoint_config(job, org_id=org, run_id="fresh")
    await app.ainvoke({"secret": "fresh"}, config=kept)
    from app.services.privacy.retention import purge_platform

    async with maker() as db:
        policy = {"token_days": 0, "audit_ip_days": 0, "checkpoint_days": 0}
        dry = await purge_platform(db, policy, dry_run=True, now=datetime.now(UTC))
        assert dry["checkpoints_unscoped"] >= 1 and await _threads_naming(db, stranger)  # counted, not deleted
        out = await purge_platform(db, policy, dry_run=False, now=datetime.now(UTC))
        await db.commit()
    assert out["checkpoints_unscoped"] >= 1
    async with maker() as db:
        assert await _threads_naming(db, stranger) == set()
        unscoped = (await db.execute(
            text("SELECT count(*) FROM checkpoints WHERE thread_id !~ :ns"), {"ns": cp.NAMESPACED_RE}
        )).scalar_one()
        assert unscoped == 0
        assert await _rows(db, "checkpoints", org) > 0, "retention removed a fresh namespaced thread"
        await ephemeral._checkpoints_delete(db, org)
        await db.commit()


async def test_reading_a_checkpoint_rebuilds_only_the_allowed_types() -> None:
    """F4: a row is data; only the library's safe types and the app's state dataclasses are constructed from it."""
    org, job = str(uuid.uuid4()), str(uuid.uuid4())
    FAIL_SECOND["on"] = False
    config = cp.checkpoint_config(job, org_id=org, run_id="r")
    await build_app().ainvoke({"secret": "s", "log": StepLog("pnl", True), "gadget": Gadget("x")}, config=config)

    _close(cp._CHECKPOINTER)
    cp.reset_checkpointer()
    values = cp.get_checkpointer().get_tuple(config).checkpoint["channel_values"]
    assert isinstance(values["log"], StepLog) and values["log"].step == "pnl"
    assert not isinstance(values["gadget"], Gadget), "an unlisted type was constructed from a checkpoint row"


async def test_retention_deletes_idle_threads_and_keeps_recent_ones(maker) -> None:
    org, job_old = str(uuid.uuid4()), str(uuid.uuid4())
    FAIL_SECOND["on"] = False
    await build_app().ainvoke({"secret": "x"}, config=cp.checkpoint_config(job_old, org_id=org, run_id="r"))

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
    """On a database WITHOUT the tables (a fresh stack): the first start creates them, the others wait their turn.
    Blocking on the lock instead of polling it deadlocked against CREATE INDEX CONCURRENTLY."""
    import sqlalchemy as sa

    engine = sa.create_engine(get_settings().database_url_sync)
    with engine.begin() as conn:
        for name in cp.LIBRARY_TABLES:
            conn.execute(sa.text(f"DROP TABLE IF EXISTS {name}"))
    engine.dispose()
    errors: list[BaseException] = []
    savers: list[Any] = []

    def build() -> None:
        try:
            savers.append(cp._postgres_saver(get_settings().database_url_sync))
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=build) for _ in range(4)]
    try:
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=120)
        assert not any(t.is_alive() for t in threads), "setup hung"
        assert errors == []
    finally:
        for saver in savers:  # each holds its own pool of up to 5 connections
            _close(saver)
