"""Auth abuse resistance: mail flooding, address enumeration, credentials ended by a reset.

Nothing here touches a network: mail goes to the outbox (recorded no-op transport).
"""
from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select, update

from app.config import get_settings
from app.models.audit_log import AuditLog
from app.models.outbox_message import OutboxMessage
from app.models.password_reset import PasswordResetToken
from app.models.user import User
from tests.api_helpers import PAROLA, bellek_istemcisi, emailed_token

pytestmark = pytest.mark.email_verification

P = "/api/v1"
NEW = "YepYeniSifre-789!"


@pytest_asyncio.fixture
async def client(monkeypatch):
    monkeypatch.setattr(get_settings(), "password_reset_response_floor_seconds", 0.0)
    monkeypatch.setattr(get_settings(), "email_verification_required", True)
    async with bellek_istemcisi() as c:
        yield c


async def register(client, email="ada@example.com", password=PAROLA, **headers):
    return await client.post(f"{P}/auth/register", json={"email": email, "password": password}, headers=headers)


async def forgot(client, email, **headers):
    return await client.post(f"{P}/auth/forgot-password", json={"email": email}, headers=headers)


async def resend(client, email, **headers):
    return await client.post(f"{P}/auth/resend-verification", json={"email": email}, headers=headers)


async def rows(client, kind: str, recipient: str | None = None) -> list[OutboxMessage]:
    async with client._maker() as db:
        q = select(OutboxMessage).where(OutboxMessage.kind == kind)
        if recipient:
            q = q.where(OutboxMessage.recipient == recipient)
        return list((await db.execute(q)).scalars().all())


async def verified(client, email):
    async with client._maker() as db:
        await db.execute(update(User).where(User.email == email).values(email_verified_at=datetime.now(UTC)))
        await db.commit()


def same(answers) -> bool:
    return len({(a.status_code, json.dumps(a.json(), sort_keys=True)) for a in answers}) == 1


# ── (a) flooding ────────────────────────────────────────────────────────────

async def test_repeated_forgot_requests_send_one_mail_per_cooldown_and_the_link_keeps_working(client):
    await register(client)
    await verified(client, "ada@example.com")
    answers = [await forgot(client, "ada@example.com") for _ in range(8)]
    assert same(answers)
    assert len(await rows(client, "password_reset")) == 1, "one mail, however many requests"
    token = await emailed_token(client, "password_reset", "ada@example.com")
    assert (await client.post(f"{P}/auth/reset-password", json={"token": token, "new_password": NEW})).status_code == 200


async def test_the_cooldown_ends_and_a_new_link_is_allowed(client, monkeypatch):
    await register(client)
    await verified(client, "ada@example.com")
    await forgot(client, "ada@example.com")
    async with client._maker() as db:
        await db.execute(update(PasswordResetToken).values(created_at=datetime.now(UTC) - timedelta(minutes=20)))
        await db.commit()
    await forgot(client, "ada@example.com")
    assert len(await rows(client, "password_reset")) == 2


async def test_many_ips_cannot_flood_one_address(client):
    await register(client)
    await verified(client, "ada@example.com")
    for i in range(12):
        await forgot(client, "ada@example.com", **{"X-Forwarded-For": f"198.51.100.{i}"})
    assert len(await rows(client, "password_reset")) == 1


async def test_verification_resend_is_suppressed_inside_the_cooldown(client):
    await register(client)  # the registration already mailed a link
    answers = [await resend(client, "ada@example.com") for _ in range(5)]
    assert same(answers)
    assert len(await rows(client, "email_verification")) == 1


async def test_one_ip_cannot_use_up_the_allowance_of_the_owner(client, monkeypatch):
    """The hourly allowance is keyed on address AND ip: the attacker's requests do not count for the owner."""
    from app.api.password_reset import address_allowed
    from app.middleware.rate_limit import _counters

    _counters.clear()
    monkeypatch.setattr(get_settings(), "password_reset_per_email_per_hour", 2)
    assert [await address_allowed("pwreset", "ada@example.com", "203.0.113.1") for _ in range(4)] == [True, True, False, False]
    assert await address_allowed("pwreset", "ada@example.com", "198.51.100.9") is True


# ── (b) enumeration ─────────────────────────────────────────────────────────

async def test_register_answers_the_same_for_a_new_and_an_existing_address(client):
    first = await register(client, "ada@example.com")
    again = await register(client, "ada@example.com", password="BaskaSifre-111!")
    other = await register(client, "new@example.com")
    assert same([first, again, other])
    assert first.status_code == 201
    assert set(first.json()["data"]) == {"accepted", "verification_required"}  # no user id, no role


async def test_register_takes_the_floor_for_new_and_existing_alike(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "password_reset_response_floor_seconds", 0.3)
    await register(client, "ada@example.com")
    for email in ("ada@example.com", "fresh@example.com"):
        started = time.monotonic()
        await register(client, email)
        assert time.monotonic() - started >= 0.29


async def test_an_existing_address_gets_a_you_already_have_an_account_mail_and_nothing_changes(client):
    await register(client, "ada@example.com")
    await verified(client, "ada@example.com")
    async with client._maker() as db:
        before = (await db.execute(select(User).where(User.email == "ada@example.com"))).scalar_one()
        digest, version = before.hashed_password, before.token_version
    await register(client, "ada@example.com", password="Saldirgan-Sifre-1!")
    await register(client, "ada@example.com", password="Saldirgan-Sifre-2!")  # inside the cool-down: no second mail
    mail = await rows(client, "account_exists", "ada@example.com")
    assert len(mail) == 1
    assert "/auth/forgot-password" in mail[0].body and "token" not in mail[0].body.lower().replace("e-mail", "")
    async with client._maker() as db:
        after = (await db.execute(select(User).where(User.email == "ada@example.com"))).scalar_one()
    assert (after.hashed_password, after.token_version) == (digest, version)
    assert (await client.post(f"{P}/auth/login", json={"email": "ada@example.com", "password": PAROLA})).status_code == 200


async def test_an_unverified_existing_address_is_never_sent_a_verification_link_by_a_second_register(client):
    """Otherwise whoever registered first (a squatter) would be verified by the real owner clicking."""
    await register(client, "ada@example.com", password="Squatter-Sifre-1!")
    await register(client, "ada@example.com", password=PAROLA)
    assert len(await rows(client, "email_verification")) == 1  # only the first registration's
    assert len(await rows(client, "account_exists")) == 1


async def test_a_deactivated_account_gets_no_mail_and_the_same_answer(client):
    await register(client, "gone@example.com")
    async with client._maker() as db:
        await db.execute(update(User).where(User.email == "gone@example.com").values(is_active=False))
        await db.commit()
    a = await register(client, "gone@example.com")
    b = await register(client, "nobody@example.com")
    assert same([a, b])
    assert not await rows(client, "account_exists")


async def test_every_auth_door_answers_alike_for_known_and_unknown_addresses(client):
    await register(client, "ada@example.com")
    await verified(client, "ada@example.com")
    for door in (forgot, resend):
        assert same([await door(client, "ada@example.com"), await door(client, "nobody@example.com")])
    bad_known = await client.post(f"{P}/auth/login", json={"email": "ada@example.com", "password": "wrong-wrong-1"})
    bad_unknown = await client.post(f"{P}/auth/login", json={"email": "nobody@example.com", "password": "wrong-wrong-1"})
    assert same([bad_known, bad_unknown]) and bad_known.status_code == 401


async def test_login_costs_the_same_work_for_an_unknown_address(client, monkeypatch):
    import app.api.auth as auth

    calls: list[str] = []
    real = auth.verify_password

    def spy(plain, hashed):
        calls.append(hashed)
        return real(plain, hashed)

    monkeypatch.setattr(auth, "verify_password", spy)
    await client.post(f"{P}/auth/login", json={"email": "nobody@example.com", "password": "wrong-wrong-1"})
    assert calls == [auth._DUMMY_HASH], "an unknown address is compared against a dummy hash, like a wrong password"


async def test_without_verification_the_old_explicit_error_stays(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "email_verification_required", False)
    await register(client, "ada@example.com")
    again = await register(client, "ada@example.com")
    assert again.status_code == 400


# ── (c) a reset ends the user's credentials ─────────────────────────────────

async def test_a_reset_revokes_the_personal_api_key_and_the_audit_row_counts_it(client):
    await register(client, "ada@example.com")
    await verified(client, "ada@example.com")
    login = await client.post(f"{P}/auth/login", json={"email": "ada@example.com", "password": PAROLA})
    bearer = {"Authorization": f"Bearer {login.json()['data']['access_token']}"}
    made = await client.post(f"{P}/auth/api-key", headers=bearer)
    assert made.status_code == 200
    key = made.json()["data"]["api_key"]
    assert (await client.get(f"{P}/auth/me", headers={"X-API-Key": key})).status_code == 200

    await forgot(client, "ada@example.com")
    token = await emailed_token(client, "password_reset", "ada@example.com")
    assert (await client.post(f"{P}/auth/reset-password", json={"token": token, "new_password": NEW})).status_code == 200

    assert (await client.get(f"{P}/auth/me", headers={"X-API-Key": key})).status_code == 401
    assert (await client.get(f"{P}/auth/me", headers=bearer)).status_code == 401, "sessions end too"
    async with client._maker() as db:
        row = (await db.execute(select(User).where(User.email == "ada@example.com"))).scalar_one()
        audit = (await db.execute(
            select(AuditLog).where(AuditLog.action == "auth.password_reset_completed")
        )).scalar_one()
    assert row.api_key is None
    assert audit.request_body["api_keys_revoked"] == 1 and audit.request_body["sessions_ended"] == "all"
    assert key not in json.dumps(audit.request_body)


async def test_a_reset_of_an_account_without_a_key_records_zero(client):
    await register(client, "ada@example.com")
    await verified(client, "ada@example.com")
    await forgot(client, "ada@example.com")
    token = await emailed_token(client, "password_reset", "ada@example.com")
    await client.post(f"{P}/auth/reset-password", json={"token": token, "new_password": NEW})
    async with client._maker() as db:
        audit = (await db.execute(select(AuditLog).where(AuditLog.action == "auth.password_reset_completed"))).scalar_one()
    assert audit.request_body["api_keys_revoked"] == 0
