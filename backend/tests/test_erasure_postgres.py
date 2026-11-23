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
