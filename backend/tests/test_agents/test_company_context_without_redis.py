"""With Redis down, the context still comes back from its database snapshot.

get/save_company_context skipped the database entirely when no session was
passed — which is how every background caller calls them (the auto-chain, the
worker's post-completion step). Redis alone carried the context there, so on an
instance without Redis the chain read an empty context right after one had been
saved, and its downstream steps skipped for "no CFO data". Seen in a live run:
"CompanyContext + semantic persisted for org=…" followed immediately by
"No context found for org=… — returning empty".
"""
from __future__ import annotations

import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.database as database
import app.models.company_context  # noqa: F401 — registers the table
import app.services.company_context as cc
from app.database import Base


@pytest_asyncio.fixture
async def maker(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    m = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(database, "session_factory", lambda: m)

    async def no_redis():
        return None

    monkeypatch.setattr(cc, "_get_redis", no_redis)
    yield m
    await engine.dispose()


async def test_a_context_saved_without_a_session_is_read_back(maker):
    ctx = await cc.get_company_context("org-1")
    ctx.update_agent_result("cfo", {"pnl": {"revenue": 42}})
    await cc.save_company_context(ctx)  # no session: the background callers' way

    again = await cc.get_company_context("org-1")
    assert again.last_cfo_result["pnl"]["revenue"] == 42


async def test_an_unknown_org_still_gets_an_empty_context(maker):
    ctx = await cc.get_company_context("org-yok")
    assert ctx.org_id == "org-yok"
    assert not ctx.last_cfo_result


async def test_invalidate_clears_the_snapshot_without_a_session(maker):
    ctx = await cc.get_company_context("org-2")
    ctx.update_agent_result("cfo", {"pnl": {"revenue": 1}})
    await cc.save_company_context(ctx)

    await cc.invalidate_company_context("org-2")
    assert not (await cc.get_company_context("org-2")).last_cfo_result
