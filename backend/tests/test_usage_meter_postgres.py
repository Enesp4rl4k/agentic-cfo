"""The plan-limit counter on a real Postgres (the SQLite twin is `test_usage_meter.py`).

Runs only where `DATABASE_URL_OVERRIDE` is a Postgres URL over a migrated schema (the "Migrations on Postgres" CI
job); skipped everywhere else. Org ids are unique per run; the rows are deleted at the end.

Two things differ from SQLite and are checked here: a failed statement aborts the whole Postgres transaction until
it is rolled back (so the plan lookup and the count after a failed record silently read "free" and 0, i.e. an
unlimited upload), and two sessions really run in parallel, so the check-then-record gap is a race.
"""
from __future__ import annotations

import asyncio
import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text

import app.database as database
from app.services.usage_meter import (
    UsageLimitExceeded,
    check_upload_limit,
    get_monthly_usage,
    record_usage_event,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL_OVERRIDE", "").startswith("postgresql"),
    reason="needs the Postgres service of the migrations job",
)


@pytest_asyncio.fixture
async def org():
    org_id = str(uuid.uuid4())
    yield org_id
    async with database.get_session_factory(database.engine())() as s:
        await s.execute(text("DELETE FROM usage_events WHERE org_id = :o"), {"o": org_id})
        await s.commit()


def session():
    return database.get_session_factory(database.engine())()


async def used(org_id: str) -> int:
    async with session() as s:
        return await get_monthly_usage(org_id, "upload", s)


async def test_a_failed_record_does_not_poison_the_session_into_an_unlimited_upload(org):
    async with session() as s:  # free plan: 3 a month, all used
        for _ in range(3):
            await record_usage_event(org, "upload", db=s)
    assert await used(org) == 3

    async with session() as s:
        # `usage_events.org_id` is VARCHAR(36): the INSERT fails, which aborts the Postgres transaction.
        await record_usage_event("x" * 40, "upload", db=s)
        with pytest.raises(UsageLimitExceeded):
            await check_upload_limit(org, s)  # the same session: still counts 3, still refuses


@pytest.mark.xfail(strict=True, reason=(
    "Real defect, needs a design change (see test_usage_meter.py): the check and the record are separate calls with "
    "the upload's work between them, so two parallel requests at limit-1 both pass and both record."))
async def test_two_parallel_uploads_for_the_last_slot_do_not_both_get_it(org):
    async with session() as s:
        for _ in range(2):
            await record_usage_event(org, "upload", db=s)
    passed, both_checked = 0, asyncio.Event()

    async def request() -> None:
        nonlocal passed
        async with session() as s:
            try:
                await check_upload_limit(org, s)
            except UsageLimitExceeded:
                return
            passed += 1
            if passed == 2:
                both_checked.set()
            try:
                await asyncio.wait_for(both_checked.wait(), 2)
            except TimeoutError:
                pass
            await record_usage_event(org, "upload", db=s)

    await asyncio.gather(request(), request())
    assert await used(org) <= 3
