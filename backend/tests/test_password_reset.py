"""Password reset: every state, enumeration resistance, single use, and what a reset ends.

The e-mail goes through the outbox (immediate class); a test reads the link from the queued row,
the only place the raw token exists. Nothing here touches a network: the sender is a recorded
no-op under pytest.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import UTC, datetime, timedelta

import pytest_asyncio
from sqlalchemy import select

from app.config import get_settings
from app.models.audit_log import AuditLog
from app.models.outbox_message import OutboxMessage
from app.models.password_reset import PasswordResetToken
from app.models.user import User
from app.services import outbox
from app.services.secret_tokens import hash_token
from tests.api_helpers import PAROLA, bellek_istemcisi, emailed_token

P = "/api/v1"
NEW = "BrandNewPassword456!"


@pytest_asyncio.fixture
async def client(monkeypatch):
    monkeypatch.setattr(get_settings(), "password_reset_response_floor_seconds", 0.0)
    async with bellek_istemcisi() as c:
        yield c


async def register(client, email: str = "ada@example.com") -> str:
    r = await client.post(f"{P}/auth/register", json={"email": email, "password": PAROLA})
    assert r.status_code == 201, r.text
    return r.json()["data"]["user_id"]


async def login(client, email: str, password: str):
    return await client.post(f"{P}/auth/login", json={"email": email, "password": password})


async def forgot(client, email: str):
    return await client.post(f"{P}/auth/forgot-password", json={"email": email})


async def reset(client, token: str, password: str = NEW):
    return await client.post(f"{P}/auth/reset-password", json={"token": token, "new_password": password})


async def outbox_rows(client, kind: str = "password_reset") -> list[OutboxMessage]:
    async with client._maker() as db:
        rows = (await db.execute(select(OutboxMessage).where(OutboxMessage.kind == kind))).scalars().all()
    return list(rows)


async def set_user(client, email: str, **fields) -> None:
    async with client._maker() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one()
        for k, v in fields.items():
            setattr(user, k, v)
        await db.commit()


# ── the request: the same answer for every address ──────────────────────────

async def test_the_answer_is_identical_for_known_unknown_sso_only_and_deactivated(client):
    await register(client, "known@example.com")
    await register(client, "gone@example.com")
    await register(client, "sso@example.com")
    await set_user(client, "gone@example.com", is_active=False)
    await set_user(client, "sso@example.com", hashed_password="", sso_provider="google")

    answers = {
        who: await forgot(client, f"{who}@example.com") for who in ("known", "nobody", "gone", "sso")
    }
    assert {a.status_code for a in answers.values()} == {200}
    assert len({json.dumps(a.json(), sort_keys=True) for a in answers.values()}) == 1
    # Only the real, active, password account got a link.
    assert [r.recipient for r in await outbox_rows(client)] == ["known@example.com"]


async def test_the_address_is_normalised_like_everywhere_else(client):
    await register(client, "ada@example.com")
    await forgot(client, "  ADA@Example.COM ")
    assert [r.recipient for r in await outbox_rows(client)] == ["ada@example.com"]


async def test_a_request_takes_at_least_the_floor_whether_or_not_the_account_exists(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "password_reset_response_floor_seconds", 0.3)
    await register(client, "known@example.com")
    for email in ("known@example.com", "nobody@example.com"):
        started = time.monotonic()
        await forgot(client, email)
        assert time.monotonic() - started >= 0.29, email


async def test_per_address_limit_is_answered_like_any_other_request_and_sends_nothing_more(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "auth_mail_cooldown_minutes", 0)  # isolate the limit from the cool-down
    monkeypatch.setattr(get_settings(), "password_reset_per_email_per_hour", 2)
    await register(client, "ada@example.com")
    answers = [await forgot(client, "ada@example.com") for _ in range(4)]
    assert {a.status_code for a in answers} == {200}
    assert len({json.dumps(a.json()) for a in answers}) == 1
    assert len(await outbox_rows(client)) == 2, "the third and fourth were counted, recorded and not sent"
    async with client._maker() as db:
        audits = (await db.execute(select(AuditLog).where(AuditLog.action == "auth.password_reset_requested"))).scalars().all()
    assert sorted(a.request_body["outcome"] for a in audits) == ["rate_limited", "rate_limited", "sent", "sent"]


async def test_per_ip_limit_is_a_429(client):
    codes = [(await forgot(client, f"x{i}@example.com")).status_code for i in range(11)]
    assert codes[:10] == [200] * 10 and codes[10] == 429


# ── the token ───────────────────────────────────────────────────────────────

async def test_the_token_is_stored_hashed_with_an_expiry_and_travels_in_the_fragment(client):
    await register(client)
    await forgot(client, "ada@example.com")
    (row,) = await outbox_rows(client)
    assert row.delivery_class == "immediate" and row.status == "pending"
    assert "/auth/reset-password#token=" in row.body and "?token=" not in row.body
    token = await emailed_token(client, "password_reset", "ada@example.com")
    async with client._maker() as db:
        (stored,) = (await db.execute(select(PasswordResetToken))).scalars().all()
    assert stored.token_hash == hash_token(token) != token
    assert token not in stored.token_hash
    ttl = stored.expires_at.replace(tzinfo=UTC) - datetime.now(UTC)
    assert timedelta(minutes=28) < ttl <= timedelta(minutes=30)
    assert stored.used_at is None


async def test_the_link_is_removed_from_the_row_once_the_mail_has_really_gone(client, monkeypatch):
    async def delivered(recipient: str, subject: str, body: str) -> str:
        return "sent"

    monkeypatch.setattr(outbox, "send_plain_email", delivered)
    await register(client)
    await forgot(client, "ada@example.com")
    async with client._maker() as db:
        counts = await outbox.deliver_pending(db)
        await db.commit()
        (row,) = (await db.execute(select(OutboxMessage).where(OutboxMessage.kind == "password_reset"))).scalars().all()
    assert counts["sent"] == 1
    assert (row.status, row.transport, row.body) == ("sent", "smtp", outbox.SCRUBBED)


async def test_a_recorded_no_op_keeps_the_text_so_development_can_open_the_link(client):
    await register(client)
    await forgot(client, "ada@example.com")
    async with client._maker() as db:
        await outbox.deliver_pending(db)
        await db.commit()
    token = await emailed_token(client, "password_reset", "ada@example.com")
    assert (await reset(client, token)).status_code == 200


async def test_the_token_is_never_in_a_response_or_a_log(client, caplog):
    await register(client)
    with caplog.at_level(logging.INFO):  # (SQL parameter logging at DEBUG is a deployment switch, off by default)
        answer = await forgot(client, "ada@example.com")
        token = await emailed_token(client, "password_reset", "ada@example.com")
        done = await reset(client, token)
    assert token not in answer.text and token not in done.text and NEW not in done.text
    assert token not in caplog.text and NEW not in caplog.text
    # And it is not accepted in a URL: there is no GET.
    assert (await client.get(f"{P}/auth/reset-password", params={"token": token})).status_code == 405


# ── completing ──────────────────────────────────────────────────────────────

async def test_a_reset_sets_the_password_and_the_old_one_stops_working(client):
    await register(client)
    await forgot(client, "ada@example.com")
    token = await emailed_token(client, "password_reset", "ada@example.com")
    done = await reset(client, token)
    assert done.status_code == 200 and done.json()["data"]["state"] == "ok"
    assert (await login(client, "ada@example.com", PAROLA)).status_code == 401
    assert (await login(client, "ada@example.com", NEW)).status_code == 200


async def test_the_token_works_once(client):
    await register(client)
    await forgot(client, "ada@example.com")
    token = await emailed_token(client, "password_reset", "ada@example.com")
    assert (await reset(client, token)).status_code == 200
    again = await reset(client, token, "Another789Password!")
    assert again.status_code == 400 and again.json()["data"] == {"state": "used"}
    assert (await login(client, "ada@example.com", NEW)).status_code == 200


async def test_two_simultaneous_completions_make_one_winner(client):
    await register(client)
    await forgot(client, "ada@example.com")
    token = await emailed_token(client, "password_reset", "ada@example.com")
    answers = await asyncio.gather(reset(client, token, NEW), reset(client, token, "Other789Password!"))
    assert sorted(a.status_code for a in answers) == [200, 400]
    winner = NEW if answers[0].status_code == 200 else "Other789Password!"
    assert (await login(client, "ada@example.com", winner)).status_code == 200


async def test_completing_closes_every_other_open_token_of_the_user(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "auth_mail_cooldown_minutes", 0)
    await register(client)
    await forgot(client, "ada@example.com")
    first = await emailed_token(client, "password_reset", "ada@example.com")
    await asyncio.sleep(0.01)
    await forgot(client, "ada@example.com")
    second = await emailed_token(client, "password_reset", "ada@example.com")
    assert first != second
    assert (await reset(client, second)).status_code == 200
    assert (await reset(client, first)).json()["data"] == {"state": "used"}


async def test_unknown_expired_and_malformed_tokens_are_each_named(client):
    await register(client)
    await forgot(client, "ada@example.com")
    token = await emailed_token(client, "password_reset", "ada@example.com")
    unknown = await reset(client, "f" * 64)
    assert (unknown.status_code, unknown.json()["data"]) == (400, {"state": "invalid"})
    async with client._maker() as db:
        row = (await db.execute(select(PasswordResetToken))).scalar_one()
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await db.commit()
    expired = await reset(client, token)
    assert (expired.status_code, expired.json()["data"]) == (400, {"state": "expired"})
    assert (await login(client, "ada@example.com", PAROLA)).status_code == 200, "an expired token changes nothing"
    assert (await client.post(f"{P}/auth/reset-password", json={"token": "x", "new_password": NEW})).status_code == 422


async def test_the_registration_password_policy_applies(client):
    await register(client)
    await forgot(client, "ada@example.com")
    token = await emailed_token(client, "password_reset", "ada@example.com")
    assert (await reset(client, token, "short")).status_code == 422
    assert (await reset(client, token)).status_code == 200, "a refused password does not burn the token"


async def test_an_account_deactivated_after_the_request_cannot_reset(client):
    await register(client)
    await forgot(client, "ada@example.com")
    token = await emailed_token(client, "password_reset", "ada@example.com")
    await set_user(client, "ada@example.com", is_active=False)
    answer = await reset(client, token)
    assert (answer.status_code, answer.json()["data"]) == (400, {"state": "invalid"})
    await set_user(client, "ada@example.com", is_active=True)
    assert (await login(client, "ada@example.com", PAROLA)).status_code == 200


# ── what a reset ends ───────────────────────────────────────────────────────

async def test_a_reset_ends_every_earlier_session_and_refresh_token(client):
    await register(client)
    old = (await login(client, "ada@example.com", PAROLA)).json()["data"]
    old_headers = {"Authorization": f"Bearer {old['access_token']}"}
    assert (await client.get(f"{P}/auth/me", headers=old_headers)).status_code == 200

    await forgot(client, "ada@example.com")
    assert (await reset(client, await emailed_token(client, "password_reset", "ada@example.com"))).status_code == 200

    assert (await client.get(f"{P}/auth/me", headers=old_headers)).status_code == 401
    assert (await client.post(f"{P}/auth/refresh", json={"refresh_token": old["refresh_token"]})).status_code == 401
    fresh = (await login(client, "ada@example.com", NEW)).json()["data"]
    assert (await client.get(f"{P}/auth/me", headers={"Authorization": f"Bearer {fresh['access_token']}"})).status_code == 200
    assert (await client.post(f"{P}/auth/refresh", json={"refresh_token": fresh["refresh_token"]})).status_code == 200


# ── the record ──────────────────────────────────────────────────────────────

async def test_request_and_completion_are_audited_without_the_token_or_the_password(client):
    user_id = await register(client)
    await forgot(client, "ada@example.com")
    token = await emailed_token(client, "password_reset", "ada@example.com")
    await reset(client, token)
    async with client._maker() as db:
        audits = (await db.execute(select(AuditLog).where(AuditLog.action.like("auth.password_reset_%")))).scalars().all()
    assert sorted(a.action for a in audits) == ["auth.password_reset_completed", "auth.password_reset_requested"]
    assert {a.user_id for a in audits} == {user_id}
    blob = json.dumps([a.request_body for a in audits])
    assert token not in blob and NEW not in blob and PAROLA not in blob and "ada@example.com" not in blob


def test_the_audit_middleware_redacts_the_new_password_and_the_token():
    from app.middleware.audit import _redact_body

    body = _redact_body({"token": "t", "new_password": "p", "email": "a@x.com"})
    assert body == {"token": "***REDACTED***", "new_password": "***REDACTED***", "email": "a@x.com"}


async def test_no_decision_is_recorded(client):
    from app.models.decision import Decision

    await register(client)
    await forgot(client, "ada@example.com")
    await reset(client, await emailed_token(client, "password_reset", "ada@example.com"))
    async with client._maker() as db:
        assert (await db.execute(select(Decision))).scalars().all() == []


# ── the pieces ──────────────────────────────────────────────────────────────

def test_the_two_migration_digests_agree():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / "alembic" / "versions" / "071_pwreset_outbox_classes.py"
    spec = importlib.util.spec_from_file_location("m071", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for raw in ("a" * 64, " padded\n", "ünïcode"):
        assert module._digest(raw) == hash_token(raw)
