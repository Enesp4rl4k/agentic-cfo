"""The outbox's delivery classes, its recipient rules, and the routes that used to send inline.

Every outward effect is an outbox row. A released message goes only to a recipient the organisation
configured; an immediate message only from the allowlisted template kinds; in tests the sender is a
recorded no-op, so none of this reaches a network.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy import select

from app.config import get_settings
from app.models.alert_preference import AlertPreference
from app.models.organization import Organization
from app.models.outbox_message import IMMEDIATE, OutboxMessage
from app.services import outbox, outbox_immediate, outbox_transport
from app.services.alert_router import AlertAction, AlertDecision, RawAlert
from app.services.notification_service import NotificationService
from tests.api_helpers import bellek_istemcisi, emailed_token, kullanici
from tests.db_helpers import gecici_oturum

P = "/api/v1"


@pytest_asyncio.fixture
async def db():
    import app.models  # noqa: F401

    async with gecici_oturum() as session:
        yield session


@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_record():
    outbox_transport.RECORDED.clear()


async def _row(db, **fields: Any) -> OutboxMessage:
    values: dict[str, Any] = {
        "key": f"k-{time.monotonic_ns()}", "org_id": "org-1", "channel": "email", "recipient": "a@x.com",
        "subject": "s", "body": "b", "source": "t", "source_ref": "r", "status": "pending",
    }
    row = OutboxMessage(**{**values, **fields})
    db.add(row)
    await db.flush()
    return row


async def _prefs(db, **fields: Any) -> None:
    db.add(AlertPreference(org_id="org-1", **fields))
    await db.flush()


# ── the sender is a recorded no-op under test ───────────────────────────────

async def test_in_tests_the_sender_records_and_sends_nothing(db):
    await _prefs(db, email_recipients=json.dumps(["a@x.com"]))
    row = await _row(db)
    counts = await outbox.deliver_pending(db)
    assert counts["sent"] == 1
    assert (row.status, row.transport) == ("sent", "noop")
    assert list(outbox_transport.RECORDED) == [("email", "a@x.com", "s")]


async def test_live_without_credentials_fails_with_the_reason_and_stops(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "outbox_transport", "live")
    monkeypatch.setattr(get_settings(), "smtp_user", "")
    await _prefs(db, email_recipients=json.dumps(["a@x.com"]))
    row = await _row(db)
    await outbox.deliver_pending(db)
    assert (row.status, row.last_error, row.attempts) == ("failed", "smtp_not_configured", 1)


async def test_a_header_injection_in_a_subject_or_recipient_is_refused():
    assert (await outbox_transport.send_plain_email("a@x.com", "hi\nBcc: e@evil.test", "b")).startswith("failed:")
    assert (await outbox_transport.send_plain_email("a@x.com\nBcc: e@evil.test", "hi", "b")).startswith("failed:")


# ── released class: recipients must be the organisation's ───────────────────

async def test_a_released_email_to_an_outsider_fails_with_a_reason_and_is_not_sent(db):
    await _prefs(db, email_recipients=json.dumps(["a@x.com"]))
    row = await _row(db, recipient="outsider@elsewhere.test")
    counts = await outbox.deliver_pending(db)
    assert counts["failed"] == 1 and not outbox_transport.RECORDED
    assert (row.status, row.last_error) == ("failed", "recipient_not_allowed")


async def test_a_member_and_a_listed_recipient_are_allowed_in_any_spelling(db):
    from app.models.user import User

    db.add(User(email="Member@X.com", hashed_password="x", org_id="org-1", is_active=True))
    await _prefs(db, email_recipients=json.dumps([" Listed@X.com "]))
    await db.flush()
    assert await outbox.allowed_email_recipients(db, "org-1") == {"member@x.com", "listed@x.com"}
    assert await outbox.allowed_email_recipients(db, "org-2") == set()


async def test_a_deactivated_member_is_no_longer_a_recipient(db):
    from app.models.user import User

    db.add(User(email="gone@x.com", hashed_password="x", org_id="org-1", is_active=False))
    await db.flush()
    assert await outbox.allowed_email_recipients(db, "org-1") == set()


async def test_whatsapp_goes_only_to_the_configured_number(db):
    await _prefs(db, whatsapp_number="+905551112233")
    good = await _row(db, key="w1", channel="whatsapp", recipient="+90 555 111 2233")
    bad = await _row(db, key="w2", channel="whatsapp", recipient="+905559998877")
    await outbox.deliver_pending(db)
    assert (good.status, good.transport) == ("sent", "noop")
    assert (bad.status, bad.last_error) == ("failed", "recipient_not_allowed")


@pytest.mark.parametrize(
    ("url", "problem"),
    [
        ("http://hooks.slack.com/x", "destination_not_https"),
        ("https://localhost/x", "destination_is_internal"),
        ("https://127.0.0.1/x", "destination_is_internal"),
        ("https://10.0.0.5/x", "destination_is_internal"),
        ("https://169.254.169.254/latest", "destination_is_internal"),
        ("https://db.internal/x", "destination_is_internal"),
        ("https://hooks.slack.com/services/T/B/x", None),
    ],
)
def test_destination_rules(url, problem):
    assert outbox.destination_problem(url) == problem


async def test_a_webhook_to_an_internal_address_fails_at_once_without_retries(db):
    row = await outbox.enqueue_webhook(
        db, key="wh", org_id="org-1", url="https://169.254.169.254/x", event_type="e", data={},
        source="t", source_ref="r",
    )
    await outbox.deliver_pending(db)
    assert (row.status, row.last_error, row.attempts) == ("failed", "destination_is_internal", 1)


# ── immediate class: an allowlist of template kinds ─────────────────────────

async def test_only_allowlisted_kinds_can_be_written_as_immediate(db):
    assert set(outbox_immediate.IMMEDIATE_KINDS) == {
        "org_invite", "password_reset", "email_verification", "connection_test", "bot_reply",
    }
    with pytest.raises(outbox_immediate.ImmediateKindRefused):
        await outbox_immediate._write(
            db, kind="briefing", key="x", org_id="org-1", channel="email", recipient="a@x.com",
            subject="s", body="Nakit: 1.000.000 TL", source_ref="r",
        )
    with pytest.raises(outbox_immediate.ImmediateKindRefused):  # a kind may not use another kind's channel
        await outbox_immediate._write(
            db, kind="password_reset", key="x", org_id="org-1", channel="whatsapp", recipient="1",
            subject="s", body="b", source_ref="r",
        )


async def test_the_sender_refuses_an_immediate_row_whose_kind_is_not_allowed(db):
    forged = await _row(db, key="f1", delivery_class=IMMEDIATE, kind="briefing", body="Nakit: 1.000.000 TL")
    nokind = await _row(db, key="f2", delivery_class=IMMEDIATE, kind=None)
    await outbox.deliver_pending(db)
    assert not outbox_transport.RECORDED
    assert [(r.status, r.last_error) for r in (forged, nokind)] == [("failed", "immediate_kind_not_allowed")] * 2


async def test_the_generic_enqueue_cannot_make_business_data_immediate_by_accident(db):
    row = await outbox.enqueue(
        db, key="g", org_id="org-1", channel="email", recipient="a@x.com", subject="s", body="b",
        source="x", source_ref="r",
    )
    assert (row.delivery_class, row.kind) == ("released", None)


async def test_connection_test_goes_to_a_member_not_to_a_stranger(db):
    from app.models.user import User

    db.add(User(email="me@x.com", hashed_password="x", org_id="org-1", is_active=True))
    await db.flush()
    row = await outbox_immediate.enqueue_connection_test(
        db, test_id="t1", org_id="org-1", channel="email", destination="ME@x.com"
    )
    assert (row.delivery_class, row.kind, row.recipient) == ("immediate", "connection_test", "me@x.com")
    with pytest.raises(outbox_immediate.ImmediateKindRefused, match="recipient_not_allowed"):
        await outbox_immediate.enqueue_connection_test(
            db, test_id="t2", org_id="org-1", channel="email", destination="stranger@elsewhere.test"
        )
    with pytest.raises(outbox_immediate.ImmediateKindRefused, match="destination_is_internal"):
        await outbox_immediate.enqueue_connection_test(
            db, test_id="t3", org_id="org-1", channel="webhook", destination="https://192.168.1.1/x"
        )


async def test_only_one_time_link_kinds_are_scrubbed(db, monkeypatch):
    reset = await outbox_immediate.enqueue_password_reset(
        db, token_id="r1", org_id=None, email="a@x.com", reset_url="https://app/x#token=abc", expires_minutes=30
    )
    test = await outbox_immediate.enqueue_connection_test(
        db, test_id="c1", org_id="org-1", channel="webhook", destination="https://hooks.example.com/x"
    )
    assert reset.org_id == outbox_immediate.SYSTEM_ORG
    async def delivered(recipient: str, subject: str, body: str) -> str:
        return "sent"

    monkeypatch.setattr(outbox, "send_plain_email", delivered)
    await outbox.deliver_pending(db)
    assert reset.body == outbox.SCRUBBED and "hooks.example.com" in test.body


async def test_a_name_cannot_inject_a_header_through_the_invitation_subject(db):
    import datetime as dt

    row = await outbox_immediate.enqueue_org_invite(
        db, invite_id="i1", org_id="org-1", email="n@x.com", org_name="Acme\r\nBcc: e@evil.test",
        role="viewer", accept_url="https://app/auth/accept-invite?token=t",
        expires_at=dt.datetime(2026, 12, 1, tzinfo=dt.UTC),
    )
    assert "\n" not in row.subject and "\r" not in row.subject


# ── the notification service queues; it sends nothing ───────────────────────

def _decision() -> AlertDecision:
    return AlertDecision(
        action=AlertAction.ESCALATE, priority_score=0.9,
        alert=RawAlert(level="critical", message="Nakit açığı", domain="cfo", source="cashflow", job_id="j"),
    )


async def test_alert_email_and_whatsapp_are_outbox_rows_once_per_recipient(db):
    await _prefs(
        db, channels=json.dumps(["email", "whatsapp"]), whatsapp_number="+905551112233",
        email_recipients=json.dumps(["a@x.com", "A@x.com", "b@x.com"]),
    )
    await db.commit()
    for _ in range(2):  # the same alert the same day is the same message
        result = await NotificationService().deliver([_decision()], org_id="org-1", org_name="Acme", db=db)
    assert result["email"] == 2 and result["whatsapp"] == 1
    rows = (await db.execute(select(OutboxMessage).order_by(OutboxMessage.key))).scalars().all()
    assert sorted((r.channel, r.recipient) for r in rows) == [
        ("email", "a@x.com"), ("email", "b@x.com"), ("whatsapp", "+905551112233"),
    ]
    assert {r.status for r in rows} == {"pending"} and {r.delivery_class for r in rows} == {"released"}
    assert not outbox_transport.RECORDED, "queued, not sent"
    counts = await outbox.deliver_pending(db)
    assert counts["sent"] == 3


# ── the routes ──────────────────────────────────────────────────────────────

async def test_an_invitation_is_an_immediate_outbox_row_with_the_link(client, monkeypatch):
    headers, org_id, _ = await kullanici(client, "sahip@example.com", role="owner")
    async with client._maker() as db:
        (await db.get(Organization, org_id)).name = "Acme\nBcc: e@evil.test"
        await db.commit()
    r = await client.post(f"{P}/org/invite", headers=headers, json={"email": "Yeni@Example.com", "role": "viewer"})
    assert r.status_code == 201 and r.json()["data"]["email_sent"] is True
    token = await emailed_token(client, "org_invite", "yeni@example.com")
    async with client._maker() as db:
        (row,) = (await db.execute(select(OutboxMessage).where(OutboxMessage.kind == "org_invite"))).scalars().all()
    assert (row.delivery_class, row.status, row.org_id) == ("immediate", "pending", org_id)
    assert "\n" not in row.subject and f"/auth/accept-invite?token={token}" in row.body
    # the outstanding link works, and once delivered the row no longer holds it
    assert (await client.post(f"{P}/org/invite/preview", json={"token": token})).json()["data"]["state"] == "valid"
    async def delivered(recipient: str, subject: str, body: str) -> str:
        return "sent"

    monkeypatch.setattr(outbox, "send_plain_email", delivered)
    async with client._maker() as db:
        await outbox.deliver_pending(db)
        await db.commit()
        (row,) = (await db.execute(select(OutboxMessage).where(OutboxMessage.kind == "org_invite"))).scalars().all()
    assert row.body == outbox.SCRUBBED


async def test_the_connection_test_routes_queue_checked_messages(client):
    headers, org_id, _ = await kullanici(client, "sahip@example.com", role="owner")
    async with client._maker() as db:
        db.add(AlertPreference(org_id=org_id, slack_webhook_url="https://hooks.example.com/services/T/B/s"))
        await db.commit()

    queued = await client.post(f"{P}/notifications/test-slack", headers=headers)
    assert queued.status_code == 200 and queued.json()["data"]["queued"] is True
    own = await client.post(f"{P}/integrations/webhook/test", headers=headers,
                            json={"channel": "email", "target": "SAHIP@example.com"})
    assert own.status_code == 200 and own.json()["data"]["queued"] is True

    for body in (
        {"channel": "email", "target": "stranger@elsewhere.test"},
        {"channel": "custom", "target": "https://169.254.169.254/latest/meta-data"},
        {"channel": "custom", "target": "http://example.com/x"},
        {"channel": "sms", "target": "x"},
    ):
        assert (await client.post(f"{P}/integrations/webhook/test", headers=headers, json=body)).status_code == 400, body

    async with client._maker() as db:
        rows = (await db.execute(select(OutboxMessage))).scalars().all()
    assert sorted((r.channel, r.kind) for r in rows) == [("email", "connection_test"), ("slack", "connection_test")]
    assert not outbox_transport.RECORDED


def _sign_whatsapp(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _wa_payload(sender: str, text: str, msg_id: str = "wamid.1") -> bytes:
    return json.dumps({"entry": [{"changes": [{"value": {"messages": [
        {"id": msg_id, "from": sender, "type": "text", "text": {"body": text}}]}}]}]}).encode()


def _slack_post(client, body: str, content_type: str = "application/json"):
    ts = str(int(time.time()))
    sig = "v0=" + hmac.new(b"slacksecret", f"v0:{ts}:{body}".encode(), hashlib.sha256).hexdigest()
    return client.post(f"{P}/webhooks/slack", content=body, headers={
        "X-Slack-Request-Timestamp": ts, "X-Slack-Signature": sig, "Content-Type": content_type})


async def _outbox_rows(client):
    async with client._maker() as db:
        return (await db.execute(select(OutboxMessage).order_by(OutboxMessage.channel))).scalars().all()


async def test_an_unlinked_sender_gets_no_reply_at_all(client, monkeypatch):
    """No verified chat-to-user link exists: nobody is answered, nothing reaches the outbox."""
    monkeypatch.setattr(get_settings(), "whatsapp_app_secret", "s3cret")
    monkeypatch.setattr(get_settings(), "slack_signing_secret", "slacksecret")
    wa = _wa_payload("905551112233", "nakit")
    r = await client.post(f"{P}/webhooks/whatsapp", content=wa,
                          headers={"X-Hub-Signature-256": _sign_whatsapp("s3cret", wa), "Content-Type": "application/json"})
    assert r.json() == {"status": "unlinked"}
    forged = await client.post(f"{P}/webhooks/whatsapp", content=wa, headers={"X-Hub-Signature-256": "sha256=bad"})
    assert forged.status_code == 403
    msg = json.dumps({"type": "event_callback", "event_id": "Ev1",
                      "event": {"type": "message", "user": "U1", "channel": "C1", "text": "vergi", "ts": "1"}})
    assert (await _slack_post(client, msg)).status_code == 200
    assert await _outbox_rows(client) == []


async def test_a_linked_member_gets_one_figure_free_reply_through_the_outbox(client, monkeypatch):
    from app.api import bot_webhooks
    from app.services.bot_gateways import NOT_AVAILABLE, LinkedMember

    async def linked(db, channel, sender_id):
        return LinkedMember(user_id="u1", org_id="o1", role="owner")

    monkeypatch.setattr(bot_webhooks, "resolve_linked_member", linked)
    monkeypatch.setattr(get_settings(), "whatsapp_app_secret", "s3cret")
    monkeypatch.setattr(get_settings(), "slack_signing_secret", "slacksecret")
    wa = _wa_payload("905551112233", "nakit")
    for _ in range(2):  # Meta retries: one reply
        r = await client.post(f"{P}/webhooks/whatsapp", content=wa,
                              headers={"X-Hub-Signature-256": _sign_whatsapp("s3cret", wa), "Content-Type": "application/json"})
        assert r.json() == {"status": "handled"}
    msg = json.dumps({"type": "event_callback", "event_id": "Ev1",
                      "event": {"type": "message", "user": "U1", "channel": "C1", "text": "vergi", "ts": "1"}})
    assert (await _slack_post(client, msg)).status_code == 200
    rows = await _outbox_rows(client)
    assert [(r.channel, r.kind, r.recipient) for r in rows] == [
        ("slack_bot", "bot_reply", "C1"), ("whatsapp", "bot_reply", "905551112233"),
    ]
    slack_body = json.loads(rows[0].body)
    assert slack_body["text"] == NOT_AVAILABLE and slack_body["blocks"] == []
    assert rows[1].body == NOT_AVAILABLE


async def test_a_chat_button_gets_no_reply_and_decides_nothing(client, monkeypatch):
    import urllib.parse

    monkeypatch.setattr(get_settings(), "slack_signing_secret", "slacksecret")
    inner = json.dumps({"type": "block_actions", "trigger_id": "T1", "user": {"id": "U1"},
                        "channel": {"id": "C1"}, "actions": [{"value": "approve_inv_123"}]})
    r = await _slack_post(client, urllib.parse.urlencode({"payload": inner}), "application/x-www-form-urlencoded")
    assert r.status_code == 200
    assert await _outbox_rows(client) == []


# ── delivery right after the write ──────────────────────────────────────────

def test_kick_spawns_one_delivery_only_when_enabled(monkeypatch):
    import app.core.background as background

    spawned: list[str] = []

    def fake_spawn(coro, *, name):
        coro.close()
        spawned.append(name)

    monkeypatch.setattr(background, "spawn", fake_spawn)
    outbox.kick()
    assert spawned == []  # the suite runs with the kick off
    monkeypatch.setattr(get_settings(), "outbox_kick_on_enqueue", True)
    outbox.kick()
    assert spawned == ["outbox-kick"]


# ── migration 071 ───────────────────────────────────────────────────────────

def _load_071():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / "alembic" / "versions" / "071_pwreset_outbox_classes.py"
    spec = importlib.util.spec_from_file_location("m071", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_071_hashes_outstanding_invites_in_place_and_downgrades():
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    from app.services.secret_tokens import hash_token

    raw = "ab" * 32
    engine = sa.create_engine("sqlite://", poolclass=sa.pool.StaticPool)
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE users (id VARCHAR(36) PRIMARY KEY, email VARCHAR(255))"))
        conn.execute(sa.text("CREATE TABLE outbox_messages (id VARCHAR(36) PRIMARY KEY)"))
        conn.execute(sa.text(
            "CREATE TABLE org_invites (id VARCHAR(36) PRIMARY KEY, token VARCHAR(64) NOT NULL UNIQUE, "
            "accepted BOOLEAN NOT NULL, expires_at DATETIME NOT NULL)"))
        conn.execute(sa.text("INSERT INTO org_invites VALUES ('i1', :t, 0, '2999-01-01 00:00:00')"), {"t": raw})
        conn.execute(sa.text("INSERT INTO users VALUES ('u1', 'a@x.com')"))
    migration = _load_071()

    with engine.begin() as conn, Operations.context(MigrationContext.configure(conn)):
        migration.upgrade()
    with engine.connect() as conn:
        assert conn.execute(sa.text("SELECT token FROM org_invites")).scalar() == hash_token(raw), (
            "the link already e-mailed (it carries `raw`) still finds its row"
        )
        insp = sa.inspect(conn)
        assert {"token_version", "password_changed_at"} <= {c["name"] for c in insp.get_columns("users")}
        assert {"delivery_class", "kind", "transport"} <= {c["name"] for c in insp.get_columns("outbox_messages")}
        assert "password_reset_tokens" in insp.get_table_names()
        assert conn.execute(sa.text("SELECT token_version FROM users")).scalar() == 0

    with engine.begin() as conn, Operations.context(MigrationContext.configure(conn)):
        migration.downgrade()
    with engine.connect() as conn:
        insp = sa.inspect(conn)
        assert "password_reset_tokens" not in insp.get_table_names()
        assert not {"token_version", "password_changed_at"} & {c["name"] for c in insp.get_columns("users")}
        assert not {"delivery_class", "kind", "transport"} & {c["name"] for c in insp.get_columns("outbox_messages")}
        # open invitations cannot be restored to plain tokens: they are expired, not left half-working
        expires = conn.execute(sa.text("SELECT expires_at FROM org_invites")).scalar()
        assert str(expires) < "2999", expires
