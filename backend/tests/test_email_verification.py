"""E-mail verification is required: a new account cannot sign in or act until its address is proved.

The link goes through the outbox (immediate class, kind `email_verification`); a test reads it from the
queued row. Accepting an invitation proves the address (the token was e-mailed to it) and takes over an
account somebody registered there without proving it. Nothing here touches a network.
"""
from __future__ import annotations

import asyncio
import json
import time
import warnings
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy import select

from app.config import Settings, get_settings
from app.models.email_verification import EmailVerificationToken
from app.models.organization import OrgInvite, OrgMembership
from app.models.outbox_message import OutboxMessage
from app.models.user import User
from app.services.auth import create_access_token
from app.services.secret_tokens import hash_token
from tests.api_helpers import PAROLA, bellek_istemcisi, emailed_token

pytestmark = pytest.mark.email_verification

P = "/api/v1"
SQUATTER = "BirinciSifre-123!"
INVITEE = "DavetliSifre-456!"


@pytest_asyncio.fixture
async def client(monkeypatch):
    monkeypatch.setattr(get_settings(), "password_reset_response_floor_seconds", 0.0)
    monkeypatch.setattr(get_settings(), "email_verification_required", True)
    async with bellek_istemcisi() as c:
        yield c


async def register(client, email: str = "ada@example.com", password: str = PAROLA):
    return await client.post(f"{P}/auth/register", json={"email": email, "password": password})


async def login(client, email: str = "ada@example.com", password: str = PAROLA):
    return await client.post(f"{P}/auth/login", json={"email": email, "password": password})


async def verify(client, token: str):
    return await client.post(f"{P}/auth/verify-email", json={"token": token})


async def user_row(client, email: str) -> User:
    async with client._maker() as db:
        return (await db.execute(select(User).where(User.email == email))).scalar_one()


async def mails(client) -> list[OutboxMessage]:
    async with client._maker() as db:
        rows = (await db.execute(select(OutboxMessage).where(OutboxMessage.kind == "email_verification"))).scalars().all()
    return list(rows)


# ── registering and signing in ──────────────────────────────────────────────

async def test_a_new_account_cannot_sign_in_until_it_verifies(client):
    answer = await register(client)
    assert answer.status_code == 201 and answer.json()["data"]["verification_required"] is True
    assert (await user_row(client, "ada@example.com")).email_verified_at is None

    refused = await login(client)
    assert refused.status_code == 403
    assert refused.json()["data"] == {"state": "email_unverified"}
    assert "doğrulan" in refused.json()["error"] and "access_token" not in refused.text

    token = await emailed_token(client, "email_verification", "ada@example.com")
    assert (await verify(client, token)).json() == {"data": {"state": "ok"}, "error": None}
    assert (await login(client)).status_code == 200


async def test_the_unverified_message_is_only_for_the_holder_of_the_password(client):
    await register(client)
    wrong = await login(client, password="WrongPassword-999!")
    nobody = await login(client, "nobody@example.com")
    assert wrong.status_code == nobody.status_code == 401
    assert wrong.json() == nobody.json()


async def test_an_unverified_account_cannot_act_with_a_token_or_refresh_it(client):
    await register(client)
    user = await user_row(client, "ada@example.com")
    access = create_access_token(user.id, user.email, user.role, token_version=user.token_version)
    assert (await client.get(f"{P}/auth/me", headers={"Authorization": f"Bearer {access}"})).status_code == 403
    from app.services.auth import create_refresh_token

    refresh = create_refresh_token(user.id, token_version=user.token_version)
    assert (await client.post(f"{P}/auth/refresh", json={"refresh_token": refresh})).status_code == 401


async def test_an_account_that_registers_when_the_rule_is_off_is_not_held(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "email_verification_required", False)
    answer = await register(client)
    assert answer.json()["data"]["verification_required"] is False
    assert (await login(client)).status_code == 200
    assert await mails(client) == []


# ── the token ───────────────────────────────────────────────────────────────

async def test_the_token_is_stored_hashed_expires_and_travels_in_the_fragment(client):
    await register(client)
    (mail,) = await mails(client)
    assert (mail.delivery_class, mail.status, mail.recipient) == ("immediate", "pending", "ada@example.com")
    assert "/auth/verify-email#token=" in mail.body and "?token=" not in mail.body
    token = await emailed_token(client, "email_verification", "ada@example.com")
    async with client._maker() as db:
        (stored,) = (await db.execute(select(EmailVerificationToken))).scalars().all()
    assert stored.token_hash == hash_token(token) != token
    ttl = stored.expires_at.replace(tzinfo=UTC) - datetime.now(UTC)
    assert timedelta(hours=47) < ttl <= timedelta(hours=48)


async def test_every_state_of_a_verification_link(client):
    await register(client)
    token = await emailed_token(client, "email_verification", "ada@example.com")
    unknown = await verify(client, "f" * 64)
    assert (unknown.status_code, unknown.json()["data"]) == (400, {"state": "invalid"})
    async with client._maker() as db:
        row = (await db.execute(select(EmailVerificationToken))).scalar_one()
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await db.commit()
    expired = await verify(client, token)
    assert (expired.status_code, expired.json()["data"]) == (400, {"state": "expired"})
    assert (await login(client)).status_code == 403, "an expired link verifies nothing"

    await client.post(f"{P}/auth/resend-verification", json={"email": "ada@example.com"})
    fresh = await emailed_token(client, "email_verification", "ada@example.com")
    assert fresh != token and (await verify(client, fresh)).status_code == 200
    used = await verify(client, fresh)
    assert (used.status_code, used.json()["data"]) == (400, {"state": "used"})


async def test_two_simultaneous_verifications_make_one_winner(client):
    await register(client)
    token = await emailed_token(client, "email_verification", "ada@example.com")
    answers = await asyncio.gather(verify(client, token), verify(client, token))
    assert sorted(a.status_code for a in answers) == [200, 400]


async def test_a_password_reset_also_proves_the_address(client):
    await register(client)
    await client.post(f"{P}/auth/forgot-password", json={"email": "ada@example.com"})
    token = await emailed_token(client, "password_reset", "ada@example.com")
    assert (await client.post(f"{P}/auth/reset-password", json={"token": token, "new_password": INVITEE})).status_code == 200
    assert (await login(client, password=INVITEE)).status_code == 200


# ── resend: the same answer for every address ───────────────────────────────

async def test_resend_answers_identically_and_sends_only_for_an_unverified_password_account(client):
    await register(client, "open@example.com")
    await register(client, "done@example.com")
    await register(client, "sso@example.com")
    await register(client, "gone@example.com")
    async with client._maker() as db:
        for email, fields in (
            ("done@example.com", {"email_verified_at": datetime.now(UTC)}),
            ("sso@example.com", {"hashed_password": "", "sso_provider": "google"}),
            ("gone@example.com", {"is_active": False}),
        ):
            row = (await db.execute(select(User).where(User.email == email))).scalar_one()
            for k, v in fields.items():
                setattr(row, k, v)
        await db.commit()
    before = len(await mails(client))
    answers = [
        await client.post(f"{P}/auth/resend-verification", json={"email": f"{who}@example.com"})
        for who in ("open", "done", "sso", "gone", "nobody")
    ]
    assert {a.status_code for a in answers} == {200}
    assert len({json.dumps(a.json(), sort_keys=True) for a in answers}) == 1
    new = (await mails(client))[before:]
    assert [m.recipient for m in new] == ["open@example.com"]


async def test_resend_takes_the_floor_and_is_limited_per_address_and_per_ip(client, monkeypatch):
    await register(client)
    monkeypatch.setattr(get_settings(), "password_reset_response_floor_seconds", 0.3)
    for email in ("ada@example.com", "nobody@example.com"):
        started = time.monotonic()
        await client.post(f"{P}/auth/resend-verification", json={"email": email})
        assert time.monotonic() - started >= 0.29
    monkeypatch.setattr(get_settings(), "password_reset_response_floor_seconds", 0.0)
    monkeypatch.setattr(get_settings(), "password_reset_per_email_per_hour", 2)
    for _ in range(4):
        assert (await client.post(f"{P}/auth/resend-verification", json={"email": "ada@example.com"})).status_code == 200
    assert len(await mails(client)) == 1 + 1 + 1, "register, the first resend (floor test), one more before the limit"
    codes = [(await client.post(f"{P}/auth/resend-verification", json={"email": f"x{i}@example.com"})).status_code for i in range(10)]
    assert 429 in codes


# ── the invitation proves the address, and takes over a squatter's account ───

async def invite_token_for(client, owner_headers, email: str, role: str = "viewer") -> str:
    r = await client.post(f"{P}/org/invite", headers=owner_headers, json={"email": email, "role": role})
    assert r.status_code == 201, r.text
    return await emailed_token(client, "org_invite", email)


async def owner_of_a_company(client):
    """A verified owner with a company (the rule is on, so the owner is made verified directly)."""
    await register(client, "sahip@example.com")
    async with client._maker() as db:
        from app.models.organization import Organization

        user = (await db.execute(select(User).where(User.email == "sahip@example.com"))).scalar_one()
        org = Organization(name="Acme", slug="acme")
        db.add(org)
        await db.flush()
        user.org_id, user.role, user.email_verified_at = org.id, "owner", datetime.now(UTC)
        await db.commit()
        org_id = org.id
    token = (await login(client, "sahip@example.com")).json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}, org_id


async def test_accepting_an_invitation_creates_a_verified_account(client):
    headers, _ = await owner_of_a_company(client)
    token = await invite_token_for(client, headers, "yeni@example.com")
    accepted = await client.post(f"{P}/org/invite/accept", json={"token": token, "password": INVITEE})
    assert accepted.status_code == 201
    assert (await user_row(client, "yeni@example.com")).email_verified_at is not None
    assert (await login(client, "yeni@example.com", INVITEE)).status_code == 200


async def test_an_invitee_takes_over_an_account_registered_at_their_address_by_someone_else(client):
    headers, org_id = await owner_of_a_company(client)
    # The squatter registers the invitee's address in advance and never verifies it.
    await register(client, "kurban@example.com", SQUATTER)
    squatter = await user_row(client, "kurban@example.com")
    stale_session = create_access_token(squatter.id, squatter.email, squatter.role, token_version=squatter.token_version)
    async with client._maker() as db:
        row = await db.get(User, squatter.id)
        row.full_name, row.api_key, row.sso_provider = "Squatter", "k" * 64, "google"
        await db.commit()
    assert (await login(client, "kurban@example.com", SQUATTER)).status_code == 403

    token = await invite_token_for(client, headers, "kurban@example.com", "analyst")
    refused = await client.post(f"{P}/org/invite/accept", json={"token": token})
    assert refused.status_code == 422, "taking over needs the invitee's own password"
    accepted = await client.post(
        f"{P}/org/invite/accept", json={"token": token, "password": INVITEE, "full_name": "Gerçek Kişi"}
    )
    assert accepted.status_code == 201, accepted.text

    taken = await user_row(client, "kurban@example.com")
    assert taken.id == squatter.id, "the row is taken over in place"
    assert (taken.org_id, taken.role, taken.full_name) == (org_id, "analyst", "Gerçek Kişi")
    assert taken.email_verified_at is not None and taken.api_key is None and taken.sso_provider is None
    assert taken.token_version == squatter.token_version + 1
    assert (await login(client, "kurban@example.com", SQUATTER)).status_code == 401, "the squatter's password is gone"
    assert (await login(client, "kurban@example.com", INVITEE)).status_code == 200
    assert (await client.get(f"{P}/auth/me", headers={"Authorization": f"Bearer {stale_session}"})).status_code == 401
    async with client._maker() as db:
        members = (await db.execute(select(OrgMembership).where(OrgMembership.user_id == squatter.id))).scalars().all()
        open_tokens = (await db.execute(
            select(EmailVerificationToken).where(EmailVerificationToken.user_id == squatter.id, EmailVerificationToken.used_at.is_(None))
        )).scalars().all()
    assert [(m.org_id, m.role) for m in members] == [(org_id, "analyst")], "only the membership the invitation gives"
    assert open_tokens == [], "the squatter's verification link is dead"


async def test_a_verified_account_still_proves_itself_with_its_password_to_accept(client):
    headers, _ = await owner_of_a_company(client)
    await register(client, "var@example.com", SQUATTER)
    async with client._maker() as db:
        row = (await db.execute(select(User).where(User.email == "var@example.com"))).scalar_one()
        row.email_verified_at = datetime.now(UTC)
        await db.commit()
    token = await invite_token_for(client, headers, "var@example.com")
    assert (await client.post(f"{P}/org/invite/accept", json={"token": token, "password": INVITEE})).status_code == 401
    assert (await client.post(f"{P}/org/invite/accept", json={"token": token, "password": SQUATTER})).status_code == 201


# ── a provider verifies the address ─────────────────────────────────────────

async def test_sso_accounts_are_verified_and_a_squatted_account_loses_its_password(client):
    from app.services.sso import OAuthUser, provision_sso_user

    async with client._maker() as db:
        fresh = await provision_sso_user(OAuthUser(provider="google", provider_id="g1", email="yeni@example.com", full_name="Y"), db)
        assert fresh.email_verified_at is not None

    await register(client, "kurban@example.com", SQUATTER)
    before = await user_row(client, "kurban@example.com")
    async with client._maker() as db:
        linked = await provision_sso_user(OAuthUser(provider="google", provider_id="g2", email="Kurban@example.com", full_name="K"), db)
        assert linked.email_verified_at is not None and linked.hashed_password == ""
        assert linked.token_version == before.token_version + 1
    assert (await login(client, "kurban@example.com", SQUATTER)).status_code == 401


# ── the migration, the startup warning, the single owner ─────────────────────

def test_migration_072_marks_existing_accounts_verified_and_downgrades():
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    path = Path(__file__).resolve().parent.parent / "alembic" / "versions" / "072_email_verification.py"
    spec = importlib.util.spec_from_file_location("m072", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    engine = sa.create_engine("sqlite://", poolclass=sa.pool.StaticPool)
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE users (id VARCHAR(36) PRIMARY KEY, email VARCHAR(255), created_at DATETIME)"))
        conn.execute(sa.text("INSERT INTO users VALUES ('u1', 'a@x.com', '2026-01-02 03:04:05'), ('u2', 'b@x.com', NULL)"))
    with engine.begin() as conn, Operations.context(MigrationContext.configure(conn)):
        migration.upgrade()
    with engine.connect() as conn:
        rows = conn.execute(sa.text("SELECT id, email_verified_at FROM users ORDER BY id")).all()
        assert all(r[1] is not None for r in rows), "nobody is locked out"
        assert str(rows[0][1]).startswith("2026-01-02")
        assert "email_verification_tokens" in sa.inspect(conn).get_table_names()
    with engine.begin() as conn, Operations.context(MigrationContext.configure(conn)):
        migration.downgrade()
    with engine.connect() as conn:
        insp = sa.inspect(conn)
        assert "email_verification_tokens" not in insp.get_table_names()
        assert "email_verified_at" not in {c["name"] for c in insp.get_columns("users")}


def test_production_startup_warns_when_verification_is_required_and_nothing_can_send():
    def settings(**kw) -> Settings:
        return Settings(use_sqlite=False, backend_secret_key="s" * 48, email_verification_required=True, **kw)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        settings(smtp_user="", smtp_password="").validate_production_security()
    assert any("no mail sender is configured" in str(w.message) for w in caught)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        settings(smtp_user="u", smtp_password="p").validate_production_security()
        settings(smtp_user="", smtp_password="", outbox_transport="noop").validate_production_security()
    assert not any("no mail sender" in str(w.message) for w in caught)


async def test_an_owner_cannot_invite_another_owner(client):
    headers, _ = await owner_of_a_company(client)
    refused = await client.post(f"{P}/org/invite", headers=headers, json={"email": "ikinci@example.com", "role": "owner"})
    assert refused.status_code == 403 and "tek bir sahibi" in refused.json()["error"]
    async with client._maker() as db:
        assert (await db.execute(select(OrgInvite))).scalars().all() == []
    for role in ("admin", "cfo", "smmm", "analyst", "viewer"):
        r = await client.post(f"{P}/org/invite", headers=headers, json={"email": f"{role}@example.com", "role": role})
        assert r.status_code == 201, role
