"""The Monday job runs on the clock, not on the test's schedule: what it does to a held e-mail.

The browser pilot flow found this: the API process runs the scheduler, and on a Monday after 07:00 UTC its
catch-up (every 10 minutes, window 17 h) runs the Monday briefing for every company that already has data.
A company that has no accountant yet gets a plain, deliverable e-mail (the hold is only for a company WITH
an accountant: owner decision K10); one that has an accountant gets it held, however late the job runs and
however often it is repeated. Nothing a person must release is ever sent by the job.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select

import app.database as database
from app import scheduler
from app.models.organization import OrgMembership
from app.models.outbox_message import OutboxMessage
from app.services import outbox
from app.services.schedule_runner import MONDAY_BRIEFING, SPECS
from tests.api_helpers import bellek_istemcisi, kullanici
from tests.radar_helpers import statement, upload

MONDAY = datetime(2025, 2, 3, 0, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def client(monkeypatch):
    async with bellek_istemcisi() as c:
        monkeypatch.setattr(database, "engine", lambda: None)
        monkeypatch.setattr(database, "get_session_factory", lambda _e: c._maker)

        async def no_redis():
            raise ConnectionError("no redis in the test")

        monkeypatch.setattr("app.worker.get_arq_pool", no_redis)
        yield c


@pytest.fixture
def mailed(monkeypatch):
    """Every e-mail that really leaves the outbox (recorded, never sent)."""
    sent: list[tuple[str, str]] = []

    async def send(recipient: str, subject: str, body: str) -> str:
        sent.append((recipient, subject))
        return "sent"

    monkeypatch.setattr(outbox, "send_plain_email", send)
    return sent


async def _company(client, email: str) -> str:
    _, org_id, _ = await kullanici(client, email, role="owner")
    await upload(
        client, org_id, {"amount_cents": 50_000_00, "transaction_date": "2025-01-31", "type": "income"},
        meta=statement("2025-01-31", 50_000_00),
    )
    return org_id


async def _add_accountant(client, org_id: str, email: str) -> None:
    _, _, smmm_id = await kullanici(client, email, attach_org=False, role="smmm")
    async with client._maker() as db:
        db.add(OrgMembership(user_id=smmm_id, org_id=org_id, role="smmm"))
        await db.commit()


async def _rows(client, org_id: str) -> list[OutboxMessage]:
    async with client._maker() as db:
        found = await db.execute(select(OutboxMessage).where(OutboxMessage.org_id == org_id))
        return list(found.scalars().all())


def test_the_catch_up_window_covers_the_rest_of_monday_after_seven():
    spec = SPECS[MONDAY_BRIEFING]
    for hour, runs in ((6, False), (7, True), (15, True), (23, True)):
        now = MONDAY + timedelta(hours=hour, minutes=1)
        due = spec.due(now)
        in_window = now - due <= spec.window and due.date() == MONDAY.date()
        assert in_window is runs, f"Monday {hour}:01"
    tuesday = MONDAY + timedelta(days=1, hours=2)
    assert tuesday - spec.due(tuesday) > spec.window, "Tuesday: last Monday's run is stale, nothing runs"


@pytest.mark.parametrize("hour", [7, 15, 23])
async def test_a_company_with_an_accountant_stays_held_however_late_the_monday_job_runs(client, mailed, hour):
    org_id = await _company(client, f"patron{hour}@clock-test.com")
    await _add_accountant(client, org_id, f"smmm{hour}@clock-test.com")
    now = MONDAY + timedelta(hours=hour, minutes=3)

    first = await scheduler._dispatch_monday_briefings(now)
    again = await scheduler._dispatch_monday_briefings(now + timedelta(minutes=10))  # the next catch-up tick

    assert first.done == 1 and again.done == 0 and again.skipped == 1
    rows = await _rows(client, org_id)
    assert [(r.status, r.last_error) for r in rows] == [("held", "awaiting_accountant_release")]
    assert mailed == [], "a held briefing is never delivered by the job"


async def test_a_company_without_an_accountant_is_mailed_and_a_later_accountant_does_not_recall_it(client, mailed):
    """Why the browser flow must not let the live scheduler run its Monday job before the accountant joins."""
    org_id = await _company(client, "tek@clock-test.com")
    await scheduler._dispatch_monday_briefings(MONDAY + timedelta(hours=9))
    assert [r.status for r in await _rows(client, org_id)] == ["sent"]
    assert [to for to, _ in mailed] == ["tek@clock-test.com"]

    await _add_accountant(client, org_id, "gec@clock-test.com")
    await scheduler._dispatch_monday_briefings(MONDAY + timedelta(hours=9, minutes=10))
    assert len(await _rows(client, org_id)) == 1, "one run per company and Monday: no second, held copy"
