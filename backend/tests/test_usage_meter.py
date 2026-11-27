"""The plan-limit counter (app/services/usage_meter.py): what it counts, for whom, over which period, and what
happens at and over the limit.

Facts the tests pin (the PR body has the full table):
- one row per billable event in `usage_events` (org_id, resource, quantity, recorded_at); the counter is
  SUM(quantity) per (org_id, resource) since the first instant of the current UTC calendar month;
- the plan comes from `billing_subscriptions` (status 'active'), anything else is "free";
- only "upload" is enforced (POST /upload and /veri/ekle: refused when used >= limit); "agent_run" and
  "connector_sync" are read by the billing endpoints but nothing records or enforces them;
- the check and the record are two separate calls with the file work between them.

Clock: the session is pinned to 2026-11-25 10:00 UTC (app/core/clock.py); a test moves it with `clock.pinned`.
Open defects are `xfail(strict=True)` with the reason: the day one is fixed, the marker has to go.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.core import clock
from app.services.usage_meter import (
    PLAN_LIMITS,
    AgentNotAllowed,
    UsageLimitExceeded,
    check_agent_access,
    check_upload_limit,
    get_monthly_usage,
    get_org_plan,
    get_usage_summary,
    prune_old_usage_events,
    record_usage_event,
)
from tests.api_helpers import kullanici
from tests.db_helpers import gecici_veritabani

# The two tables exist only as a migration (014_usage_events), not as models: the same columns, by hand.
_DDL = (
    "CREATE TABLE usage_events (id VARCHAR(32) PRIMARY KEY, org_id VARCHAR(36) NOT NULL, resource VARCHAR(50) NOT NULL, "
    "quantity INTEGER NOT NULL DEFAULT 1, recorded_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)",
    "CREATE TABLE billing_subscriptions (id VARCHAR(36) PRIMARY KEY, org_id VARCHAR(36) NOT NULL UNIQUE, "
    "plan VARCHAR(20) NOT NULL DEFAULT 'free', status VARCHAR(20) NOT NULL DEFAULT 'active', "
    "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)",
)

NOW = clock.TEST_INSTANT  # 2026-11-25 10:00 UTC, a Wednesday


async def create_tables(maker) -> None:
    async with maker() as s:
        for ddl in _DDL:
            await s.execute(text(ddl))
        await s.commit()


async def seed(maker, org: str, resource: str = "upload", n: int = 1, at: datetime | None = None, qty: int = 1) -> None:
    async with maker() as s:
        for _ in range(n):
            await s.execute(
                text("INSERT INTO usage_events (id, org_id, resource, quantity, recorded_at) VALUES (:i, :o, :r, :q, :t)"),
                {"i": uuid.uuid4().hex, "o": org, "r": resource, "q": qty, "t": at or NOW},
            )
        await s.commit()


async def set_plan(maker, org: str, plan: str, status: str = "active") -> None:
    async with maker() as s:
        await s.execute(
            text("INSERT INTO billing_subscriptions (id, org_id, plan, status) VALUES (:i, :o, :p, :s)"),
            {"i": uuid.uuid4().hex, "o": org, "p": plan, "s": status},
        )
        await s.commit()


async def used(maker, org: str, resource: str = "upload") -> int:
    async with maker() as s:
        return await get_monthly_usage(org, resource, s)


async def rows(maker, org: str) -> int:
    async with maker() as s:
        return (await s.execute(text("SELECT COUNT(*) FROM usage_events WHERE org_id = :o"), {"o": org})).scalar_one()


@pytest_asyncio.fixture
async def maker():
    async with gecici_veritabani() as m:
        await create_tables(m)
        yield m


def org_id() -> str:
    return str(uuid.uuid4())


async def allowed(maker, org: str) -> bool:
    async with maker() as s:
        try:
            await check_upload_limit(org, s)
        except UsageLimitExceeded:
            return False
    return True


# ── increments ────────────────────────────────────────────────────────────────

async def test_each_recorded_event_adds_its_quantity(maker):
    org = org_id()
    assert await used(maker, org) == 0
    async with maker() as s:
        await record_usage_event(org, "upload", db=s)
        await record_usage_event(org, "upload", quantity=4, db=s)
    assert await used(maker, org) == 5


async def test_resources_are_counted_apart(maker):
    org = org_id()
    await seed(maker, org, "upload", 2)
    await seed(maker, org, "agent_run", 1)
    assert (await used(maker, org, "upload"), await used(maker, org, "agent_run"), await used(maker, org, "connector_sync")) == (2, 1, 0)


async def test_recording_without_a_session_is_a_no_op():
    await record_usage_event(org_id(), "upload", db=None)
    assert await get_monthly_usage(org_id(), "upload", None) == 0


# ── the limit: limit-1, limit, limit+1 ────────────────────────────────────────

@pytest.mark.parametrize("plan,limit", [("free", 3), ("starter", 5)])
async def test_the_limit_boundary(maker, plan, limit):
    org = org_id()
    await set_plan(maker, org, plan)
    assert PLAN_LIMITS[plan]["uploads_per_month"] == limit
    await seed(maker, org, n=limit - 1)
    assert await allowed(maker, org) is True            # limit - 1 used: the last one is allowed
    await seed(maker, org, n=1)
    assert await allowed(maker, org) is False           # limit used: refused
    await seed(maker, org, n=1)
    async with maker() as s:                            # limit + 1 used (a race got there): still refused
        with pytest.raises(UsageLimitExceeded) as e:
            await check_upload_limit(org, s)
    assert (e.value.resource, e.value.plan, e.value.limit, e.value.current) == ("upload", plan, limit, limit + 1)


async def test_the_refusal_message_names_the_numbers(maker):
    org = org_id()
    await seed(maker, org, n=3)
    async with maker() as s:
        with pytest.raises(UsageLimitExceeded, match=r"3/3 .*free"):
            await check_upload_limit(org, s)


@pytest.mark.parametrize("plan", ["pro", "enterprise"])
async def test_paid_plans_are_unlimited(maker, plan):
    org = org_id()
    await set_plan(maker, org, plan)
    await seed(maker, org, n=50)
    assert await allowed(maker, org) is True


async def test_no_subscription_inactive_or_unknown_plan_means_free(maker):
    a, b, c = org_id(), org_id(), org_id()
    await set_plan(maker, b, "pro", status="canceled")
    await set_plan(maker, c, "platinum")
    async with maker() as s:
        assert [await get_org_plan(o, s) for o in (a, b, c)] == ["free", "free", "free"]
    for o in (a, b, c):
        await seed(maker, o, n=3)
        assert await allowed(maker, o) is False


async def test_quantity_counts_not_rows(maker):
    org = org_id()
    await seed(maker, org, n=1, qty=3)
    assert await allowed(maker, org) is False


async def test_other_resources_do_not_use_up_uploads(maker):
    org = org_id()
    await seed(maker, org, "agent_run", 10)
    await seed(maker, org, "connector_sync", 10)
    assert await allowed(maker, org) is True


async def test_a_refused_check_records_nothing(maker):
    org = org_id()
    await seed(maker, org, n=3)
    for _ in range(3):
        assert await allowed(maker, org) is False
    assert await rows(maker, org) == 3


# ── period: calendar month, UTC ───────────────────────────────────────────────

async def test_an_event_in_the_month_counts_from_its_first_instant(maker):
    org = org_id()
    await seed(maker, org, at=datetime(2026, 11, 1, 0, 0, 0, tzinfo=UTC))
    await seed(maker, org, at=datetime(2026, 10, 31, 23, 59, 59, 999999, tzinfo=UTC))
    assert await used(maker, org) == 1


async def test_the_counter_resets_at_the_utc_month_boundary(maker):
    org = org_id()
    await seed(maker, org, n=3, at=datetime(2026, 11, 20, 12, 0, tzinfo=UTC))
    with clock.pinned(datetime(2026, 11, 30, 23, 59, 59, tzinfo=UTC), tick=False):
        assert await used(maker, org) == 3 and await allowed(maker, org) is False
    with clock.pinned(datetime(2026, 12, 1, 0, 0, 0, tzinfo=UTC), tick=False):
        assert await used(maker, org) == 0 and await allowed(maker, org) is True


async def test_the_counter_resets_at_the_new_year(maker):
    org = org_id()
    await seed(maker, org, n=3, at=datetime(2026, 12, 31, 23, 0, tzinfo=UTC))
    with clock.pinned(datetime(2026, 12, 31, 23, 59, 59, tzinfo=UTC), tick=False):
        assert await used(maker, org) == 3
    with clock.pinned(datetime(2027, 1, 1, 0, 0, 0, tzinfo=UTC), tick=False):
        assert await used(maker, org) == 0


async def test_a_short_month_and_a_leap_day_do_not_shift_the_period(maker):
    org = org_id()
    await seed(maker, org, n=2, at=datetime(2028, 2, 29, 23, 0, tzinfo=UTC))
    with clock.pinned(datetime(2028, 2, 29, 23, 59, tzinfo=UTC), tick=False):
        assert await used(maker, org) == 2
    with clock.pinned(datetime(2028, 3, 1, 0, 0, tzinfo=UTC), tick=False):
        assert await used(maker, org) == 0


async def test_a_recorded_event_lands_in_the_pinned_month(maker):
    org = org_id()
    with clock.pinned(datetime(2027, 3, 15, 8, 0, tzinfo=UTC), tick=False):
        async with maker() as s:
            await record_usage_event(org, "upload", db=s)
        assert await used(maker, org) == 1


async def test_the_month_is_utc_so_turkey_midnight_is_three_hours_early(maker):
    # 2026-11-30 22:30 UTC is 2026-12-01 01:30 in Istanbul: still November for the counter (documented current rule).
    org = org_id()
    await seed(maker, org, n=3, at=datetime(2026, 11, 30, 20, 0, tzinfo=UTC))
    with clock.pinned(datetime(2026, 11, 30, 22, 30, tzinfo=UTC), tick=False):
        assert await used(maker, org) == 3
        async with maker() as s:
            assert (await get_usage_summary(org, s))["period"] == "2026-11"


@pytest.mark.xfail(strict=True, reason=(
    "Product decision, not guessed: the quota month is UTC (`datetime.now(UTC).replace(day=1, hour=0...)`). A Turkish "
    "customer's 1 December starts at 21:00 UTC on 30 November, so for three hours the new month's quota is "
    "still the old one's exhausted quota. Which timezone a month is (UTC, as the radar uses today, or Europe/Istanbul) "
    "is open (docs/ops/configuration.md, APP_CLOCK_START); flip this test with the decision."))
async def test_turkish_first_of_the_month_starts_a_fresh_quota(maker):
    org = org_id()
    await seed(maker, org, n=3, at=datetime(2026, 11, 20, 9, 0, tzinfo=UTC))
    with clock.pinned(datetime(2026, 11, 30, 21, 30, tzinfo=UTC), tick=False):  # 00:30 on 1 December in Istanbul
        assert await allowed(maker, org) is True


async def test_prune_removes_only_events_older_than_the_cutoff(maker):
    org = org_id()
    await seed(maker, org, at=NOW - timedelta(days=91))
    await seed(maker, org, at=NOW - timedelta(days=89))
    await seed(maker, org)
    async with maker() as s:
        assert await prune_old_usage_events(s, days=90) == 1
    assert await rows(maker, org) == 2
    assert await prune_old_usage_events(None) == 0


# ── isolation between organisations ───────────────────────────────────────────

async def test_one_organisations_usage_never_counts_for_another(maker):
    a, b = org_id(), org_id()
    await seed(maker, a, n=3)
    assert await used(maker, a) == 3 and await used(maker, b) == 0
    assert await allowed(maker, a) is False and await allowed(maker, b) is True
    async with maker() as s:
        await record_usage_event(b, "upload", db=s)
    assert await used(maker, a) == 3 and await used(maker, b) == 1


async def test_one_organisations_plan_never_applies_to_another(maker):
    a, b = org_id(), org_id()
    await set_plan(maker, a, "pro")
    await seed(maker, a, n=10)
    await seed(maker, b, n=3)
    assert await allowed(maker, a) is True and await allowed(maker, b) is False
    async with maker() as s:
        assert await get_org_plan(b, s) == "free"


async def test_an_org_id_that_is_a_prefix_or_pattern_of_another_matches_only_itself(maker):
    a = org_id()
    await seed(maker, a, n=3)
    for other in (a[:8], a + "x", "%", a.upper()):
        assert await used(maker, other) == 0


# ── agent access (defined, not wired: nothing outside this module calls it) ───

async def test_agent_access_follows_the_plan(maker):
    free, pro = org_id(), org_id()
    await set_plan(maker, pro, "pro")
    async with maker() as s:
        await check_agent_access(free, "CFO", s)
        with pytest.raises(AgentNotAllowed):
            await check_agent_access(free, "cto", s)
        await check_agent_access(pro, "cto", s)


# ── the summary and the two billing endpoints ────────────────────────────────

async def test_the_summary_reports_used_limit_and_period(maker):
    org = org_id()
    await set_plan(maker, org, "starter")
    await seed(maker, org, n=2)
    async with maker() as s:
        summary = await get_usage_summary(org, s)
    assert (summary["plan"], summary["period"]) == ("starter", "2026-11")
    assert summary["resources"]["upload"] == {"used": 2, "limit": 5, "unlimited": False, "pct": 40.0}
    assert summary["resources"]["agent_run"]["limit"] == 10
    # `connector_sync` has no `connector_syncs_per_month` limit in any plan: it reads as unlimited.
    assert summary["resources"]["connector_sync"]["unlimited"] is True


async def test_a_free_org_has_no_agent_runs(maker):
    async with maker() as s:
        summary = await get_usage_summary(org_id(), s)
    assert summary["resources"]["agent_run"] == {"used": 0, "limit": 0, "unlimited": False, "pct": 0}


async def test_the_billing_endpoints_read_the_callers_org_only(client):
    ha, a, _ = await kullanici(client, "ua@example.com")
    hb, _, _ = await kullanici(client, "ub@example.com")
    await create_tables(client._maker)
    await seed(client._maker, a, n=3)

    r = (await client.get("/api/v1/billing/check-limit/upload", headers=ha)).json()["data"]
    assert (r["allowed"], r["used"], r["limit"], r["upgrade_url"]) == (False, 3, 3, "/billing")
    r = (await client.get("/api/v1/billing/check-limit/upload", headers=hb)).json()["data"]
    assert (r["allowed"], r["used"]) == (True, 0)
    assert (await client.get("/api/v1/billing/usage", headers=hb)).json()["data"]["resources"]["upload"]["used"] == 0
    assert (await client.get("/api/v1/billing/usage", headers=ha)).json()["data"]["resources"]["upload"]["used"] == 3
    assert (await client.get("/api/v1/billing/check-limit/bogus", headers=ha)).status_code == 400
    free_runs = (await client.get("/api/v1/billing/check-limit/agent_run", headers=ha)).json()["data"]
    assert (free_runs["allowed"], free_runs["limit"]) == (False, 0)


# ── POST /upload: refused usage is not counted, accepted usage is ─────────────

CSV = b"date,description,amount\n2026-11-01,Sale,100.00\n2026-11-02,Rent,-40.00\n"


async def post_upload(client, headers):
    return await client.post("/api/v1/upload", files={"file": ("x.csv", CSV, "text/csv")}, headers=headers)


async def test_upload_at_the_limit_is_refused_with_402_and_not_counted(client):
    h, org, _ = await kullanici(client, "full@example.com")
    await create_tables(client._maker)
    await seed(client._maker, org, n=3)
    r = await post_upload(client, h)
    assert r.status_code == 402, r.text
    detail = r.json()["details"]
    assert (detail["error"], detail["used"], detail["limit"], detail["plan"]) == ("plan_limit_exceeded", 3, 3, "free")
    assert await rows(client._maker, org) == 3


async def test_a_successful_upload_is_counted_once_and_the_last_free_one_is_the_third(client):
    h, org, _ = await kullanici(client, "third@example.com")
    await create_tables(client._maker)
    await seed(client._maker, org, n=2)
    r = await post_upload(client, h)
    assert r.status_code == 201, r.text
    assert await used(client._maker, org) == 3
    assert (await post_upload(client, h)).status_code == 402
    assert await used(client._maker, org) == 3


async def test_an_upload_that_fails_validation_is_not_counted(client):
    h, org, _ = await kullanici(client, "bad@example.com")
    await create_tables(client._maker)
    r = await client.post("/api/v1/upload", files={"file": ("x.exe", b"MZ\x00\x00", "application/octet-stream")}, headers=h)
    assert r.status_code >= 400
    assert await rows(client._maker, org) == 0


# ── failure modes ─────────────────────────────────────────────────────────────

class _Savepoint:
    def __init__(self, db) -> None:
        self.db = db

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, *_a):
        if exc_type is not None:
            self.db.rolled_back += 1  # the savepoint is rolled back, nothing else
        return False


class BrokenDb:
    """A session whose every statement fails (the connection dropped, the disk is full)."""

    def __init__(self) -> None:
        self.rolled_back = 0

    async def execute(self, *_a, **_k):
        raise OperationalError("SELECT", {}, Exception("connection lost"))

    async def commit(self) -> None:
        raise OperationalError("COMMIT", {}, Exception("connection lost"))

    def begin_nested(self):
        return _Savepoint(self)


async def test_a_failing_database_never_crashes_recording_counting_or_pruning():
    db = BrokenDb()
    await record_usage_event(org_id(), "upload", db=db)           # fire-and-forget: logged, never raised
    assert await get_org_plan(org_id(), db) == "free"
    assert await get_monthly_usage(org_id(), "upload", db) == 0
    assert await prune_old_usage_events(db) == 0
    summary = await get_usage_summary(org_id(), db)
    assert summary["plan"] == "free"


async def test_a_missing_usage_table_is_tolerated_while_the_migration_is_pending():
    async with gecici_veritabani() as m:  # no usage_events table at all (a SQLite dev schema is built from models)
        async with m() as s:
            await record_usage_event(org_id(), "upload", db=s)
            assert await get_monthly_usage(org_id(), "upload", s) == 0
            await check_upload_limit(org_id(), s)  # documented: metering is off until the table exists


@pytest.mark.xfail(strict=True, reason=(
    "Fail-open, left for a product decision: when the counting query fails for any reason (not only the "
    "deliberate 'table not migrated yet' case) `get_monthly_usage` logs at DEBUG and returns 0, so "
    "`check_upload_limit` waves the upload through and an org at its limit gets unlimited usage for as long as the "
    "database is unwell. Failing closed would also stop uploads wherever the table is missing (SQLite dev "
    "schemas), so telling 'missing table' from 'database error' and the refusal's status code are decisions."))
async def test_a_database_error_does_not_grant_the_upload():
    with pytest.raises(Exception):  # noqa: B017 - UsageLimitExceeded or a 503, whichever is chosen
        await check_upload_limit(org_id(), BrokenDb())


async def test_a_failed_statement_is_rolled_back_to_its_savepoint_so_the_session_stays_usable():
    db = BrokenDb()
    await record_usage_event(org_id(), "upload", db=db)
    await get_org_plan(org_id(), db)
    await get_monthly_usage(org_id(), "upload", db)
    assert db.rolled_back == 3  # on Postgres a failed statement aborts the transaction until it is rolled back


# ── concurrency ───────────────────────────────────────────────────────────────

async def test_two_recordings_at_once_both_land(maker):
    org = org_id()

    async def one() -> None:
        async with maker() as s:
            await record_usage_event(org, "upload", db=s)

    await asyncio.gather(one(), one())
    assert await used(maker, org) == 2


@pytest.mark.xfail(strict=True, reason=(
    "Real defect, needs a design change: the gate is `check_upload_limit` (SELECT SUM) at the top of the request and "
    "`record_usage_event` (INSERT) after the file was stored and the job created, with nothing holding the slot "
    "between them (the module docstring promises an 'atomic check + record'; there is no such function). Two "
    "requests at limit-1 both pass the check and both record: limit+1 used. The fix reserves the slot before the "
    "work (insert-then-count, or a per-org row lock / counter row) and releases it when the work fails, which "
    "changes both callers (api/upload.py, services/ingest/ekle.py) and probably needs a migration."))
async def test_two_uploads_racing_for_the_last_slot_do_not_both_get_it(maker):
    org = org_id()
    await seed(maker, org, n=2)  # free plan: 3 per month, one slot left
    passed, both_checked = 0, asyncio.Event()

    async def request() -> None:
        nonlocal passed
        async with maker() as s:
            try:
                await check_upload_limit(org, s)
            except UsageLimitExceeded:
                return
            passed += 1
            if passed == 2:
                both_checked.set()
            try:  # the upload's file work between the check and the record: the other request's check lands here
                await asyncio.wait_for(both_checked.wait(), 1)
            except TimeoutError:
                pass  # the other request was refused: the fixed behaviour
            await record_usage_event(org, "upload", db=s)

    await asyncio.gather(request(), request())
    assert await used(maker, org) <= 3
