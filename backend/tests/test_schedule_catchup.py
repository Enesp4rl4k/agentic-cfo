"""Scheduled jobs are catch-up safe and idempotent: a restart at 07:00 does not lose the Monday briefing,
a second scheduler or a repeated start does not send it twice, and a run that crashed midway is retried once.

The work is a small stand-in that writes a row (an in-app notification) so the effect can be counted; the
ledger, claim, windows and alerts are the real code. Nothing leaves the process.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import func, select

import app.database as database
from app import scheduler
from app.config import get_settings
from app.models.in_app_notification import InAppNotification
from app.models.job_run import DONE, FAILED, RUNNING, ScheduledJobRun
from app.models.outbox_message import OutboxMessage
from app.services import job_runs, schedule_runner
from tests.api_helpers import bellek_istemcisi, kullanici

MONDAY_0710 = datetime(2026, 11, 23, 7, 10, tzinfo=UTC)
MONDAY = "2026-11-23"


@pytest_asyncio.fixture
async def client(monkeypatch):
    async with bellek_istemcisi() as c:
        monkeypatch.setattr(database, "engine", lambda: None)
        monkeypatch.setattr(database, "get_session_factory", lambda _e: c._maker)
        monkeypatch.setattr(get_settings(), "platform_operator_emails", "ops@tiphys.io")
        yield c


@pytest.fixture
def effects(monkeypatch):
    """Replace the Monday work for one company by a counted write; `fail_first` makes it crash once."""
    state = {"calls": 0, "fail_first": 0}

    async def work(org_id, anchor, db):
        state["calls"] += 1
        db.add(InAppNotification(org_id=org_id, level="info", domain="cfo", source="monday_briefing",
                                 message="bülten", action="route", priority_score=0.8))
        await db.flush()
        if state["fail_first"] > 0:
            state["fail_first"] -= 1
            raise RuntimeError("worker died midway")

    monkeypatch.setattr(scheduler, "_monday_briefing_for_org", work)
    return state


async def notes(client, org_id) -> int:
    async with client._maker() as db:
        return (await db.execute(select(func.count()).select_from(InAppNotification).where(
            InAppNotification.org_id == org_id, InAppNotification.source == "monday_briefing"))).scalar_one()


async def ledger(client) -> list[tuple[str, str, str]]:
    async with client._maker() as db:
        rows = (await db.execute(select(ScheduledJobRun).where(ScheduledJobRun.job == "monday_briefing"))).scalars().all()
    return sorted((r.period, r.status, str(r.attempts)) for r in rows)


async def alerts(client) -> list[OutboxMessage]:
    async with client._maker() as db:
        return list((await db.execute(select(OutboxMessage).where(OutboxMessage.kind == "operator_alert"))).scalars().all())


def test_the_due_times_are_the_cron_times():
    assert schedule_runner.period_for("monday_briefing", MONDAY_0710) == MONDAY
    assert schedule_runner.period_for("monday_briefing", datetime(2026, 11, 25, 12, tzinfo=UTC)) == MONDAY  # Wednesday: last Monday
    assert schedule_runner.period_for("monday_briefing", datetime(2026, 11, 23, 6, 59, tzinfo=UTC)) == "2026-11-16"
    assert schedule_runner.period_for("hourly_kri_scan", MONDAY_0710) == "2026-11-23T06"


async def test_a_missed_monday_briefing_is_caught_up_once(client, effects):
    _, org_id, _ = await kullanici(client, "sahip@example.com", role="owner")
    first = await schedule_runner.catch_up(MONDAY_0710)  # the worker was down at 07:00
    assert first["monday_briefing"].done >= 1 and effects["calls"] == 1 and await notes(client, org_id) == 1
    again = await schedule_runner.catch_up(MONDAY_0710 + timedelta(minutes=10))
    assert again["monday_briefing"].done == 0 and effects["calls"] == 1 and await notes(client, org_id) == 1
    assert (MONDAY, DONE, "1") in await ledger(client)


async def test_a_late_catch_up_alerts_the_operators_once(client, effects):
    await kullanici(client, "sahip@example.com", role="owner")
    await schedule_runner.catch_up(MONDAY_0710)
    await schedule_runner.catch_up(MONDAY_0710 + timedelta(minutes=10))
    rows = await alerts(client)
    assert {r.recipient for r in rows} == {"ops@tiphys.io"}
    assert len([r for r in rows if r.subject.endswith("Kaçan bülten telafi edildi")]) == 1


async def test_the_ordinary_cron_tick_is_not_an_alert(client, effects):
    await kullanici(client, "sahip@example.com", role="owner")
    await schedule_runner.catch_up(MONDAY_0710.replace(minute=0, second=30))
    assert await alerts(client) == []


async def test_a_second_scheduler_cannot_double_the_run(client, effects):
    _, org_id, _ = await kullanici(client, "sahip@example.com", role="owner")
    await asyncio.gather(
        scheduler._dispatch_monday_briefings(MONDAY_0710), scheduler._dispatch_monday_briefings(MONDAY_0710)
    )
    assert effects["calls"] == 1 and await notes(client, org_id) == 1


async def test_a_run_that_crashes_midway_is_retried_and_lands_once(client, effects):
    _, org_id, _ = await kullanici(client, "sahip@example.com", role="owner")
    effects["fail_first"] = 1
    report = await scheduler._dispatch_monday_briefings(MONDAY_0710)
    assert report.failed == 1 and await notes(client, org_id) == 0, "the half-done write was rolled back"
    assert (MONDAY, FAILED, "1") in await ledger(client)
    retry = await scheduler._dispatch_monday_briefings(MONDAY_0710 + timedelta(minutes=10))
    assert retry.done == 1 and await notes(client, org_id) == 1
    assert (MONDAY, DONE, "2") in await ledger(client)


async def test_repeated_failure_alerts_the_operators_and_stops_after_the_cap(client, effects):
    await kullanici(client, "sahip@example.com", role="owner")
    effects["fail_first"] = 99
    for _ in range(job_runs.MAX_ATTEMPTS + 2):
        await scheduler._dispatch_monday_briefings(MONDAY_0710)
    assert effects["calls"] == job_runs.MAX_ATTEMPTS, "no more attempts after the cap"
    assert any(r.subject.endswith("Zamanlanmış iş tekrar tekrar başarısız") for r in await alerts(client))


async def test_a_dead_process_claim_is_taken_over_after_the_lease(client):
    async with client._maker() as db:
        assert await job_runs.claim(db, "j", "o", "p", now=MONDAY_0710) is not None
    async with client._maker() as db:  # still held
        assert await job_runs.claim(db, "j", "o", "p", now=MONDAY_0710 + timedelta(minutes=5)) is None
    async with client._maker() as db:  # the claimant never finished: after the lease it is ours
        taken = await job_runs.claim(db, "j", "o", "p", now=MONDAY_0710 + job_runs.LEASE + timedelta(minutes=1))
        assert taken is not None and taken.status == RUNNING and taken.attempts == 2


async def test_stale_runs_are_skipped_not_queued_up(client, effects):
    await kullanici(client, "sahip@example.com", role="owner")
    tuesday = datetime(2026, 11, 24, 9, 10, tzinfo=UTC)  # Monday's window (same day) is over
    reports = await schedule_runner.catch_up(tuesday)
    assert "monday_briefing" not in reports and "hourly_kri_scan" not in reports and effects["calls"] == 0


def test_every_job_has_a_deliberate_misfire_policy(monkeypatch):
    monkeypatch.setattr(scheduler, "_scheduler", None)
    try:
        jobs = scheduler.get_scheduler().get_jobs()
        assert {"weekly_summary", "schedule_catch_up", "ops_watch"} <= {j.id for j in jobs}
        for job in jobs:
            assert job.misfire_grace_time and job.misfire_grace_time >= 60, job.id
            assert job.coalesce is True and job.max_instances == 1, job.id
    finally:
        scheduler._scheduler = None
