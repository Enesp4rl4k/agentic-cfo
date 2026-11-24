"""The agent-memory erasure statement on a real PostgreSQL (the CI job "Migrations on Postgres").

`agent_memory_episodes` is created by the memory store's own DDL, not by the ORM, and the erasure reaches it through a
Core statement in the erase transaction. On SQLite that path is a different branch, so the Postgres one is only proven
here: two tenants, one erased, only that tenant's memory rows go. Skipped unless DATABASE_URL_OVERRIDE is Postgres.
"""
from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.services import agent_memory as am
from app.services.privacy import ephemeral

URL = os.environ.get("DATABASE_URL_OVERRIDE", "")

pytestmark = pytest.mark.skipif(not URL.startswith("postgresql"), reason="needs the CI Postgres service")

_INSERT = text(
    "INSERT INTO agent_memory_episodes (id, org_id, agent, period, summary, narrative, created_at) "
    "VALUES (:id, :org, 'pnl_agent', '2026-Q3', '{}', :narrative, 0)"
)


@pytest_asyncio.fixture
async def maker():
    engine = create_async_engine(URL)
    async with engine.begin() as conn:
        await conn.execute(text(am._PostgreSQLBackend._CREATE))  # what the store does lazily on first use
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def _count(db: AsyncSession, org: str) -> int:
    return int((await db.execute(text("SELECT count(*) FROM agent_memory_episodes WHERE org_id = :o"), {"o": org})).scalar_one())


async def test_only_the_erased_organisations_agent_memory_goes_on_postgres(maker, monkeypatch) -> None:
    a, b = str(uuid.uuid4()), str(uuid.uuid4())

    class _Store:  # the store's backend is the PostgreSQL one: that is the branch under test
        _backend = am._PostgreSQLBackend("postgresql://unused")

    monkeypatch.setattr(am, "get_memory_store", lambda: _Store())
    async with maker() as db:
        for org, n in ((a, 2), (b, 3)):
            for _ in range(n):
                await db.execute(_INSERT, {"id": str(uuid.uuid4()), "org": org, "narrative": f"about {org}"})
        await db.commit()
    try:
        async with maker() as db:
            deleted = await ephemeral._agent_memory_delete(db, a)
            await db.commit()
        assert deleted == 2
        async with maker() as db:
            assert await _count(db, a) == 0
            assert await _count(db, b) == 3  # the other tenant is untouched
    finally:
        async with maker() as db:
            await db.execute(text("DELETE FROM agent_memory_episodes WHERE org_id IN (:a, :b)"), {"a": a, "b": b})
            await db.commit()


async def test_a_failing_statement_raises_instead_of_reporting_success_on_postgres(maker, monkeypatch) -> None:
    class _Store:
        _backend = am._PostgreSQLBackend("postgresql://unused")

    monkeypatch.setattr(am, "get_memory_store", lambda: _Store())
    async with maker() as db:
        async def broken(*_a, **_k):
            raise RuntimeError("statement failed")

        monkeypatch.setattr(db, "execute", broken)
        with pytest.raises(ephemeral.AgentMemoryDeleteError):
            await ephemeral._agent_memory_delete(db, str(uuid.uuid4()))


async def test_the_per_organisation_advisory_lock_serialises_two_erasures_on_postgres(maker) -> None:
    from sqlalchemy import func

    from app.services import org_erasure as svc

    org = str(uuid.uuid4())
    async with maker() as one, maker() as two:
        await svc._lock_org(one, org)  # held until `one` ends its transaction
        busy = (await two.execute(select(func.pg_try_advisory_xact_lock(svc.org_lock_key(org))))).scalar_one()
        assert busy is False  # a second erasure of the same company would have to wait
        other = (await two.execute(select(func.pg_try_advisory_xact_lock(svc.org_lock_key(str(uuid.uuid4())))))).scalar_one()
        assert other is True  # another company is not blocked
        await one.rollback()
        free = (await two.execute(select(func.pg_try_advisory_xact_lock(svc.org_lock_key(org))))).scalar_one()
        assert free is True


async def test_two_executors_race_for_one_request_and_a_live_claim_survives_the_stale_release_on_postgres(maker, monkeypatch) -> None:
    """Real concurrent sessions: exactly one claim wins; a run renewing its claim is not released after two hours, a dead one is."""
    import asyncio
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import delete

    from app.models.erasure_record import OrgErasureRequest
    from app.services.privacy import erasure_flow

    now = datetime.now(UTC)
    ids: list[str] = []

    def _row(**over: object) -> OrgErasureRequest:
        r = OrgErasureRequest(id=str(uuid.uuid4()), target_org_id=str(uuid.uuid4()), org_hash="a" * 64, mode="anonymise", requested_by_hash="b" * 64,
                              requested_at=now, expires_at=now + timedelta(days=7), **over)  # type: ignore[arg-type]
        ids.append(r.id)
        return r

    try:
        async with maker() as db:
            due = _row(status="scheduled", execute_after=now - timedelta(minutes=1), confirmed_at=now)
            dead = _row(status="executing", claimed_at=now - timedelta(hours=3), execute_after=now + timedelta(days=1))
            live = _row(status="executing", claimed_at=now - timedelta(hours=3), execute_after=now + timedelta(days=1))
            db.add_all([due, dead, live])
            await db.commit()
            due_id, dead_id, live_id = due.id, dead.id, live.id

        async def claim() -> bool:
            async with maker() as s:
                return await erasure_flow._claim(s, due_id, now)

        results = await asyncio.gather(*[claim() for _ in range(6)])
        assert sorted(results) == [False] * 5 + [True]  # six executors, one winner

        async with maker() as db:  # `live` keeps renewing its claim, as a running erasure does; `dead` does not
            engine = db.bind
        monkeypatch.setattr(erasure_flow, "HEARTBEAT", timedelta(milliseconds=50))
        beat = asyncio.create_task(erasure_flow._heartbeat(engine, live_id))
        await asyncio.sleep(0.5)
        beat.cancel()
        async with maker() as db:
            assert (await erasure_flow.execute_due(db))["executed"] == 0
        async with maker() as db:
            assert (await db.get(OrgErasureRequest, live_id)).status == "executing"
            released = await db.get(OrgErasureRequest, dead_id)
            assert (released.status, released.failure_code) == ("failed", "interrupted")
    finally:
        async with maker() as db:
            await db.execute(delete(OrgErasureRequest).where(OrgErasureRequest.id.in_(ids)))
            await db.commit()
