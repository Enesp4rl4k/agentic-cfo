"""Plan v11 A0.5 / v10 S1.3: the Monday briefing reaches the owner by e-mail, once.

Every external effect goes through the outbox: a row keyed by what it is for, so a
second dispatch (a retry, a second worker) writes nothing new, and a message that
could not go out stays visible with the reason instead of being skipped in silence.

Owner decision K10 (recommended default, applied): in a company with an accountant,
the e-mail waits for the accountant's release; the screen does not wait.
"""

from __future__ import annotations

from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.models.organization import OrgMembership
from app.models.outbox_message import OutboxMessage
from app.services import outbox
from app.services.briefing_delivery import enqueue_briefing_emails
from app.services.monday_briefing import assemble_monday_briefing
from tests.api_helpers import bellek_istemcisi, kullanici
from tests.radar_helpers import statement, upload

ANCHOR = date(2025, 2, 3)


@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


async def _company(client, email: str, role: str = "owner") -> tuple[dict, str, str]:
    headers, org_id, user_id = await kullanici(client, email, role=role)
    await upload(
        client,
        org_id,
        {"amount_cents": 50_000_00, "transaction_date": "2025-01-31", "type": "income"},
        meta=statement("2025-01-31", 50_000_00),
    )
    return headers, org_id, user_id


async def _briefing_emails(client, org_id: str) -> list[OutboxMessage]:
    async with client._maker() as db:
        briefing = await assemble_monday_briefing(db, org_id, anchor_date=ANCHOR)
        await enqueue_briefing_emails(db, org_id, briefing)
        await db.commit()
        rows = await db.execute(select(OutboxMessage).where(OutboxMessage.org_id == org_id))
        return list(rows.scalars().all())


@pytest.mark.asyncio
async def test_the_owner_gets_one_message_with_the_three_sentences(client):
    _, org_id, _ = await _company(client, "owner@outbox-test.com")
    rows = await _briefing_emails(client, org_id)
    assert len(rows) == 1
    msg = rows[0]
    assert msg.recipient == "owner@outbox-test.com"
    assert msg.status == "pending"
    assert msg.channel == "email"
    assert "2025-02-03" in msg.subject
    async with client._maker() as db:
        briefing = await assemble_monday_briefing(db, org_id, anchor_date=ANCHOR)
    for sentence in (briefing.sentence_radar, briefing.sentence_obligation, briefing.sentence_action):
        assert sentence in msg.body


@pytest.mark.asyncio
async def test_dispatching_twice_writes_one_message(client):
    _, org_id, _ = await _company(client, "twice@outbox-test.com")
    await _briefing_emails(client, org_id)
    rows = await _briefing_emails(client, org_id)
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_an_analyst_is_not_a_recipient(client):
    _, org_id, _ = await _company(client, "analyst@outbox-test.com", role="analyst")
    assert await _briefing_emails(client, org_id) == []


@pytest.mark.asyncio
async def test_with_an_accountant_the_message_waits_for_release(client):
    _, org_id, _ = await _company(client, "patron@outbox-test.com")
    _, _, smmm_id = await kullanici(client, "smmm@outbox-test.com", attach_org=False, role="smmm")
    async with client._maker() as db:
        db.add(OrgMembership(user_id=smmm_id, org_id=org_id, role="smmm"))
        await db.commit()
    rows = await _briefing_emails(client, org_id)
    assert [r.status for r in rows] == ["held"]
    assert rows[0].last_error == "awaiting_accountant_release"


@pytest.mark.asyncio
async def test_without_smtp_the_message_is_failed_with_the_reason_not_skipped(client, monkeypatch):
    _, org_id, _ = await _company(client, "nosmtp@outbox-test.com")
    await _briefing_emails(client, org_id)

    async def not_configured(recipient: str, subject: str, body: str) -> str:
        return "not_configured"

    monkeypatch.setattr(outbox, "send_plain_email", not_configured)
    async with client._maker() as db:
        result = await outbox.deliver_pending(db)
        await db.commit()
        row = (await db.execute(select(OutboxMessage).where(OutboxMessage.org_id == org_id))).scalar_one()
    assert result == {"sent": 0, "failed": 1, "retry": 0}
    assert row.status == "failed"
    assert row.last_error == "smtp_not_configured"


@pytest.mark.asyncio
async def test_a_sent_message_is_not_sent_again(client, monkeypatch):
    _, org_id, _ = await _company(client, "sent@outbox-test.com")
    await _briefing_emails(client, org_id)
    calls: list[str] = []

    async def ok(recipient: str, subject: str, body: str) -> str:
        calls.append(recipient)
        return "sent"

    monkeypatch.setattr(outbox, "send_plain_email", ok)
    async with client._maker() as db:
        first = await outbox.deliver_pending(db)
        await db.commit()
        second = await outbox.deliver_pending(db)
        await db.commit()
        row = (await db.execute(select(OutboxMessage).where(OutboxMessage.org_id == org_id))).scalar_one()
    assert first["sent"] == 1
    assert second == {"sent": 0, "failed": 0, "retry": 0}
    assert calls == ["sent@outbox-test.com"]
    assert row.status == "sent"
    assert row.sent_at is not None
    # The message is still there after a second dispatch: still one row, still sent.
    await _briefing_emails(client, org_id)
    async with client._maker() as db:
        count = (
            await db.execute(
                select(func.count()).select_from(OutboxMessage).where(OutboxMessage.org_id == org_id)
            )
        ).scalar_one()
    assert count == 1


@pytest.mark.asyncio
async def test_a_transient_failure_is_retried_then_given_up(client, monkeypatch):
    _, org_id, _ = await _company(client, "flaky@outbox-test.com")
    await _briefing_emails(client, org_id)

    async def boom(recipient: str, subject: str, body: str) -> str:
        return "failed:connection refused"

    monkeypatch.setattr(outbox, "send_plain_email", boom)
    async with client._maker() as db:
        for _ in range(outbox.MAX_ATTEMPTS - 1):
            assert (await outbox.deliver_pending(db))["retry"] == 1
            await db.commit()
        assert (await outbox.deliver_pending(db))["failed"] == 1
        await db.commit()
        row = (await db.execute(select(OutboxMessage).where(OutboxMessage.org_id == org_id))).scalar_one()
    assert row.status == "failed"
    assert row.attempts == outbox.MAX_ATTEMPTS
    assert "connection refused" in (row.last_error or "")


@pytest.mark.asyncio
async def test_the_accountant_releases_and_the_owner_sees_the_state(client):
    owner_headers, org_id, _ = await _company(client, "own2@outbox-test.com")
    smmm_headers, _, smmm_id = await kullanici(client, "acc2@outbox-test.com", attach_org=False, role="smmm")
    async with client._maker() as db:
        db.add(OrgMembership(user_id=smmm_id, org_id=org_id, role="smmm"))
        await db.commit()
    rows = await _briefing_emails(client, org_id)
    briefing_id = rows[0].source_ref

    # The owner sees why the mail has not gone.
    r = await client.get(f"/api/v1/briefing/monday/deliveries?briefing_id={briefing_id}", headers=owner_headers)
    assert r.status_code == 200, r.text
    assert [d["status"] for d in r.json()["data"]] == ["held"]

    # The owner cannot release it; only the accountant can.
    r = await client.post("/api/v1/briefing/monday/release", json={"briefing_id": briefing_id}, headers=owner_headers)
    assert r.status_code == 403, r.text

    # The accountant acts in the client's organisation.
    async with client._maker() as db:
        from app.models.user import User

        acc = await db.get(User, smmm_id)
        acc.org_id = org_id
        await db.commit()
    from tests.api_helpers import PAROLA

    token = (
        await client.post("/api/v1/auth/login", json={"email": "acc2@outbox-test.com", "password": PAROLA})
    ).json()["data"]["access_token"]
    r = await client.post(
        "/api/v1/briefing/monday/release",
        json={"briefing_id": briefing_id},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["released"] == 1
    r = await client.get(f"/api/v1/briefing/monday/deliveries?briefing_id={briefing_id}", headers=owner_headers)
    assert [d["status"] for d in r.json()["data"]] == ["pending"]
    _ = smmm_headers


@pytest.mark.asyncio
async def test_the_monday_dispatch_writes_and_delivers_through_the_outbox(client, monkeypatch):
    """The scheduler's own path: dispatch → outbox row → delivery outcome on the row."""
    import app.database as database
    from app import scheduler

    _, org_id, _ = await _company(client, "cron@outbox-test.com")
    monkeypatch.setattr(database, "engine", lambda: None)
    monkeypatch.setattr(database, "get_session_factory", lambda _engine: client._maker)

    async def not_configured(recipient: str, subject: str, body: str) -> str:
        return "not_configured"

    monkeypatch.setattr(outbox, "send_plain_email", not_configured)
    await scheduler._dispatch_monday_briefings()
    await scheduler._dispatch_monday_briefings()  # a second tick changes nothing
    async with client._maker() as db:
        rows = (await db.execute(select(OutboxMessage).where(OutboxMessage.org_id == org_id))).scalars().all()
    assert [(r.recipient, r.status, r.last_error) for r in rows] == [
        ("cron@outbox-test.com", "failed", "smtp_not_configured")
    ]


def test_the_scheduler_registers_outbox_delivery():
    from app.scheduler import get_scheduler

    assert get_scheduler().get_job("outbox_delivery") is not None
