"""Who may sign up, and the one way a new company gets in: operator -> pilot invite -> owner of a new company.

REGISTRATION_MODE is `open` for the rest of the suite (conftest); these tests set the mode they are about.
Nothing leaves the process: the invitation is read from the outbox row, like the other e-mailed tokens.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.config import get_settings
from app.models.organization import Organization, OrgMembership
from app.models.pilot import PilotInvite
from app.models.user import User
from tests.api_helpers import PAROLA, bellek_istemcisi, emailed_token, kullanici

P = "/api/v1"
OPERATOR = "ops@tiphys.io"


@pytest_asyncio.fixture
async def client(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "password_reset_response_floor_seconds", 0.0)
    monkeypatch.setattr(settings, "email_verification_required", False)
    monkeypatch.setattr(settings, "platform_operator_emails", OPERATOR)
    async with bellek_istemcisi() as c:
        yield c


def mode(monkeypatch, value: str) -> None:
    monkeypatch.setattr(get_settings(), "registration_mode", value)


async def counts(client) -> tuple[int, int]:
    async with client._maker() as db:
        users = (await db.execute(select(func.count()).select_from(User))).scalar_one()
        orgs = (await db.execute(select(func.count()).select_from(Organization))).scalar_one()
    return users, orgs


async def operator_headers(client, monkeypatch) -> dict[str, str]:
    mode(monkeypatch, "open")  # the operator's own account exists before the pilot is closed
    headers, _, _ = await kullanici(client, OPERATOR, role="analyst")
    return headers


async def issue(client, headers, email="sahip@yenisirket.com", company="Yeni Şirket A.Ş."):
    return await client.post(f"{P}/pilot/invite/generate", headers=headers, json={"email": email, "company_name": company})


# ── the doors are shut ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("value", ["invite_only", "closed"])
async def test_register_without_an_invite_creates_nothing(client, monkeypatch, value):
    mode(monkeypatch, value)
    before = await counts(client)
    r = await client.post(f"{P}/auth/register", json={"email": "yabanci@example.com", "password": PAROLA})
    assert r.status_code == 403
    assert r.json()["data"]["state"] == "invite_only" and "yalnızca davetle" in r.json()["error"]
    assert await counts(client) == before


async def test_the_refusal_is_the_same_for_a_known_and_an_unknown_address(client, monkeypatch):
    """Enumeration resistance: the answer depends on nothing about the address."""
    await kullanici(client, "var@example.com", role="owner")
    mode(monkeypatch, "invite_only")
    known = await client.post(f"{P}/auth/register", json={"email": "var@example.com", "password": PAROLA})
    unknown = await client.post(f"{P}/auth/register", json={"email": "yok@example.com", "password": PAROLA})
    assert (known.status_code, known.json()) == (unknown.status_code, unknown.json()) and known.status_code == 403


async def test_the_policy_endpoint_names_the_contact(client, monkeypatch):
    mode(monkeypatch, "invite_only")
    monkeypatch.setattr(get_settings(), "support_contact", "davet@tiphys.io")
    data = (await client.get(f"{P}/auth/registration")).json()["data"]
    assert data["mode"] == "invite_only" and data["contact"] == "davet@tiphys.io"
    assert "davet@tiphys.io" in (await client.post(f"{P}/auth/register", json={"email": "a@b.co", "password": PAROLA})).json()["error"]
    mode(monkeypatch, "open")
    assert (await client.get(f"{P}/auth/registration")).json()["data"] == {
        "mode": "open", "open": True, "invite_only": False, "message": None, "contact": None,
    }


async def test_open_mode_still_registers_for_development(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "email_verification_required", True)
    mode(monkeypatch, "open")
    r = await client.post(f"{P}/auth/register", json={"email": "dev@example.com", "password": PAROLA})
    assert r.status_code == 201 and r.json()["data"]["accepted"] is True
    assert (await counts(client))[0] == 1


async def test_a_bogus_token_is_refused_like_any_bad_invite(client, monkeypatch):
    mode(monkeypatch, "invite_only")
    r = await client.post(f"{P}/auth/register", json={"email": "a@b.co", "password": PAROLA, "invite_token": "x" * 64})
    assert r.status_code == 400 and await counts(client) == (0, 0)


async def test_an_organisation_cannot_be_created_outside_the_invite_flow(client, monkeypatch):
    headers, _, _ = await kullanici(client, "serbest@example.com", attach_org=False, role="analyst")
    ops, _, _ = await kullanici(client, OPERATOR, attach_org=False, role="analyst")
    mode(monkeypatch, "invite_only")
    r = await client.post(f"{P}/org/create", headers=headers, json={"name": "Kendi Şirketim"})
    assert r.status_code == 403
    # operators keep the route
    assert (await client.post(f"{P}/org/create", headers=ops, json={"name": "Operatör Ltd"})).status_code == 201


# ── the flow, step by step ──────────────────────────────────────────────────────

async def test_operator_invites_owner_registers_and_invites_the_team(client, monkeypatch):
    ops = await operator_headers(client, monkeypatch)
    mode(monkeypatch, "invite_only")

    issued = await issue(client, ops)
    assert issued.status_code == 201
    body = issued.json()["data"]
    assert body["email"] == "sahip@yenisirket.com" and "token" not in str(body) and "code" not in body
    assert body["mail_delivery"] == "dev_recorded" and body["mail_notice"]
    token = await emailed_token(client, "pilot_invite", "sahip@yenisirket.com")

    preview = (await client.post(f"{P}/pilot/invite/preview", json={"token": token})).json()["data"]
    assert preview == {"state": "valid", "email": "sahip@yenisirket.com", "company_name": "Yeni Şirket A.Ş.", "registration_closed": False}
    async with client._maker() as db:  # only the digest is stored
        invite = (await db.execute(select(PilotInvite).where(PilotInvite.email == "sahip@yenisirket.com"))).scalar_one()
        assert invite.token_hash and token not in str(invite.__dict__)

    users_before, orgs_before = await counts(client)
    done = await client.post(
        f"{P}/auth/register", json={"email": "Sahip@YeniSirket.com", "password": PAROLA, "full_name": "Ayşe", "invite_token": token}
    )
    assert done.status_code == 201, done.text
    data = done.json()["data"]
    assert data["role"] == "owner" and data["access_token"] and data["org_name"] == "Yeni Şirket A.Ş."
    assert await counts(client) == (users_before + 1, orgs_before + 1)
    async with client._maker() as db:
        user = (await db.execute(select(User).where(User.email == "sahip@yenisirket.com"))).scalar_one()
        assert user.email_verified_at is not None and str(user.org_id) == data["org_id"]
        member = (await db.execute(select(OrgMembership).where(OrgMembership.user_id == user.id))).scalar_one()
        assert member.role == "owner"

    login = await client.post(f"{P}/auth/login", json={"email": "sahip@yenisirket.com", "password": PAROLA})
    assert login.status_code == 200
    owner = {"Authorization": f"Bearer {login.json()['data']['access_token']}"}
    team = await client.post(f"{P}/org/invite", headers=owner, json={"email": "ekip@yenisirket.com", "role": "analyst"})
    assert team.status_code == 201 and team.json()["data"]["email_sent"] is True

    # single use, and the preview says so
    again = await client.post(f"{P}/auth/register", json={"email": "sahip@yenisirket.com", "password": PAROLA, "invite_token": token})
    assert again.status_code == 400
    assert (await client.post(f"{P}/pilot/invite/preview", json={"token": token})).json()["data"]["state"] == "used"


async def test_the_invite_belongs_to_its_address(client, monkeypatch):
    ops = await operator_headers(client, monkeypatch)
    mode(monkeypatch, "invite_only")
    await issue(client, ops)
    token = await emailed_token(client, "pilot_invite", "sahip@yenisirket.com")
    before = await counts(client)
    r = await client.post(f"{P}/auth/register", json={"email": "baskasi@example.com", "password": PAROLA, "invite_token": token})
    assert r.status_code == 400 and await counts(client) == before


async def test_closed_mode_refuses_even_a_valid_pilot_invite(client, monkeypatch):
    ops = await operator_headers(client, monkeypatch)
    mode(monkeypatch, "invite_only")
    await issue(client, ops)
    token = await emailed_token(client, "pilot_invite", "sahip@yenisirket.com")
    mode(monkeypatch, "closed")
    before = await counts(client)
    r = await client.post(f"{P}/auth/register", json={"email": "sahip@yenisirket.com", "password": PAROLA, "invite_token": token})
    assert r.status_code == 403 and await counts(client) == before


async def test_an_expired_or_revoked_invite_does_not_work(client, monkeypatch):
    from datetime import UTC, datetime, timedelta

    ops = await operator_headers(client, monkeypatch)
    mode(monkeypatch, "invite_only")
    await issue(client, ops)
    token = await emailed_token(client, "pilot_invite", "sahip@yenisirket.com")
    async with client._maker() as db:
        invite = (await db.execute(select(PilotInvite))).scalar_one()
        invite.expires_at = datetime.now(UTC) - timedelta(days=1)
        await db.commit()
    assert (await client.post(f"{P}/pilot/invite/preview", json={"token": token})).json()["data"]["state"] == "expired"
    r = await client.post(f"{P}/auth/register", json={"email": "sahip@yenisirket.com", "password": PAROLA, "invite_token": token})
    assert r.status_code == 400
    listed = (await client.get(f"{P}/pilot/invites", headers=ops)).json()["data"]
    assert listed[0]["state"] == "expired" and "token" not in str(listed)
    assert (await client.delete(f"{P}/pilot/invite/{listed[0]['id']}", headers=ops)).status_code == 200


async def test_an_existing_account_is_told_to_sign_in_not_overwritten(client, monkeypatch):
    ops = await operator_headers(client, monkeypatch)
    await kullanici(client, "sahip@yenisirket.com", attach_org=False, role="analyst")
    mode(monkeypatch, "invite_only")
    await issue(client, ops)
    token = await emailed_token(client, "pilot_invite", "sahip@yenisirket.com")
    r = await client.post(f"{P}/auth/register", json={"email": "sahip@yenisirket.com", "password": PAROLA, "invite_token": token})
    assert r.status_code == 409


async def test_only_operators_issue_invites(client, monkeypatch):
    await operator_headers(client, monkeypatch)
    owner, _, _ = await kullanici(client, "baska@example.com", role="owner")
    assert (await issue(client, owner)).status_code == 403


# ── SSO ─────────────────────────────────────────────────────────────────────────

async def test_sso_cannot_provision_an_account_without_an_invite(client, monkeypatch):
    from app.services.sso import OAuthUser, SignUpClosed, provision_sso_user

    oauth = OAuthUser(provider="google", provider_id="g-1", email="yeni@example.com", full_name="Yeni")
    mode(monkeypatch, "invite_only")
    async with client._maker() as db:
        with pytest.raises(SignUpClosed):
            await provision_sso_user(oauth, db)
    assert (await counts(client))[0] == 0
    mode(monkeypatch, "open")
    async with client._maker() as db:
        assert (await provision_sso_user(oauth, db)).email == "yeni@example.com"


async def test_an_existing_account_may_still_sign_in_with_sso(client, monkeypatch):
    from app.services.sso import OAuthUser, provision_sso_user

    await kullanici(client, "uye@example.com", role="owner")
    mode(monkeypatch, "invite_only")
    async with client._maker() as db:
        user = await provision_sso_user(OAuthUser(provider="google", provider_id="g-2", email="uye@example.com", full_name="Üye"), db)
    assert user.sso_provider == "google"


# ── no SMTP: nothing pretends ───────────────────────────────────────────────────

async def test_with_no_mail_sender_no_invite_is_created(client, monkeypatch):
    ops = await operator_headers(client, monkeypatch)
    mode(monkeypatch, "invite_only")
    monkeypatch.setattr("app.services.mail_capability.delivery", lambda: "not_configured")
    r = await issue(client, ops)
    assert r.status_code == 503 and "iletilemedi" in r.json()["error"]
    async with client._maker() as db:
        assert (await db.execute(select(func.count()).select_from(PilotInvite))).scalar_one() == 0


async def test_with_no_mail_sender_an_organisation_invite_is_refused_not_faked(client, monkeypatch):
    owner, _, _ = await kullanici(client, "sahip@example.com", role="owner")
    monkeypatch.setattr("app.services.mail_capability.delivery", lambda: "not_configured")
    r = await client.post(f"{P}/org/invite", headers=owner, json={"email": "yeni@example.com", "role": "viewer"})
    assert r.status_code == 503 and "iletilemedi" in r.json()["error"]


async def test_the_dev_sender_is_flagged_in_every_mail_answer(client, monkeypatch):
    mode(monkeypatch, "open")
    owner, _, _ = await kullanici(client, "sahip@example.com", role="owner")
    inv = (await client.post(f"{P}/org/invite", headers=owner, json={"email": "y@example.com", "role": "viewer"})).json()["data"]
    assert inv["mail_delivery"] == "dev_recorded" and inv["email_sent"] is True
    monkeypatch.setattr(get_settings(), "email_verification_required", True)
    reg = (await client.post(f"{P}/auth/register", json={"email": "a@b.co", "password": PAROLA})).json()["data"]
    assert reg["mail_delivery"] == "dev_recorded" and "kaydedildi" in reg["mail_notice"]


async def test_a_live_sender_adds_no_notice(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "email_verification_required", True)
    monkeypatch.setattr("app.services.mail_capability.delivery", lambda: "live")
    mode(monkeypatch, "open")
    reg = (await client.post(f"{P}/auth/register", json={"email": "a@b.co", "password": PAROLA})).json()["data"]
    assert reg["mail_delivery"] == "live" and reg["mail_notice"] is None
