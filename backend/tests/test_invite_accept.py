"""An invitation is accepted by someone with or without an account, and by an accountant with many clients.

Root cause of the accountant's 400: `accept_invite` refused any existing user whose `users.org_id` was
another organisation ("Zaten başka bir organizasyona üyesiniz"), a single-organisation assumption older than
`org_memberships`. Registering through the screen always creates a company, so every accountant had one.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest_asyncio
from sqlalchemy import select

from app.models.decision import Decision
from app.models.organization import OrgInvite, OrgMembership
from app.models.user import User
from app.services.secret_tokens import hash_token
from tests.api_helpers import PAROLA, bellek_istemcisi, kullanici

P = "/api/v1"


@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


async def invite_for(client, org_id: str, email: str, role: str = "smmm", *, token: str | None = None,
                     expires: timedelta = timedelta(days=7), accepted: bool = False) -> str:
    token = token or f"{role}{email}".replace("@", "")[:20].ljust(64, "x")
    async with client._maker() as db:
        db.add(OrgInvite(org_id=org_id, email=email, role=role, token_hash=hash_token(token), accepted=accepted,
                         expires_at=datetime.now(UTC) + expires))
        await db.commit()
    return token


async def user_row(client, email: str) -> User:
    async with client._maker() as db:
        return (await db.execute(select(User).where(User.email == email))).scalar_one()


async def memberships(client, user_id: str) -> dict[str, str]:
    async with client._maker() as db:
        rows = (await db.execute(select(OrgMembership).where(OrgMembership.user_id == user_id))).scalars().all()
    return {m.org_id: m.role for m in rows}


async def test_an_accountant_with_a_company_of_their_own_joins_a_client_and_keeps_their_own(client):
    _, client_org, _ = await kullanici(client, "musteri@example.com", role="owner")
    headers, own_org, accountant_id = await kullanici(client, "musavir@example.com", role="owner")
    token = await invite_for(client, client_org, "musavir@example.com", "smmm")

    r = await client.post(f"{P}/org/invite/accept", json={"token": token, "password": PAROLA})

    assert r.status_code == 201, r.text
    assert r.json()["data"]["joined_org_id"] == client_org
    user = await user_row(client, "musavir@example.com")
    assert (user.org_id, user.role) == (own_org, "owner"), "the existing company is undisturbed"
    assert await memberships(client, accountant_id) == {own_org: "owner", client_org: "smmm"}

    # Both are listed: the switcher appears with two.
    listed = (await client.get(f"{P}/org/memberships", headers=headers)).json()["data"]
    assert {m["org_id"]: m["role"] for m in listed["memberships"]} == {own_org: "owner", client_org: "smmm"}
    assert listed["active_org_id"] == own_org

    # Every role check reads the membership of the company being acted in.
    assert (await client.post(f"{P}/actions/nope/approve", headers=headers)).status_code != 403  # owner at home
    assert (await client.post(f"{P}/org/switch", headers=headers, json={"org_id": client_org})).status_code == 200
    assert (await client.post(f"{P}/actions/nope/approve", headers=headers)).status_code == 403  # smmm in the client
    assert (await client.post(f"{P}/org/switch", headers=headers, json={"org_id": own_org})).status_code == 200
    assert (await client.post(f"{P}/actions/nope/approve", headers=headers)).status_code != 403


async def test_a_second_client_adds_a_third_membership(client):
    _, first, _ = await kullanici(client, "bir@example.com", role="owner")
    _, second, _ = await kullanici(client, "iki@example.com", role="owner")
    _, own, accountant_id = await kullanici(client, "musavir@example.com", role="owner")
    for org in (first, second):
        token = await invite_for(client, org, "musavir@example.com", "smmm", token=f"t{org}"[:64].ljust(64, "y"))
        assert (await client.post(f"{P}/org/invite/accept", json={"token": token, "password": PAROLA})).status_code == 201
    assert await memberships(client, accountant_id) == {own: "owner", first: "smmm", second: "smmm"}


async def test_the_token_alone_does_not_sign_in_an_existing_account(client):
    _, client_org, _ = await kullanici(client, "musteri@example.com", role="owner")
    _, _, accountant_id = await kullanici(client, "musavir@example.com", role="owner")
    token = await invite_for(client, client_org, "musavir@example.com", "smmm")

    wrong = await client.post(f"{P}/org/invite/accept", json={"token": token, "password": "Baska-Sifre-123"})
    assert wrong.status_code == 401
    assert client_org not in await memberships(client, accountant_id)
    nothing = await client.post(f"{P}/org/invite/accept", json={"token": token})
    assert nothing.status_code == 401

    # A session of the invited address is as good as the password.
    headers = {"Authorization": f"Bearer {(await client.post(f'{P}/auth/login', json={'email': 'musavir@example.com', 'password': PAROLA})).json()['data']['access_token']}"}
    ok = await client.post(f"{P}/org/invite/accept", json={"token": token}, headers=headers)
    assert ok.status_code == 201, ok.text
    assert (await memberships(client, accountant_id))[client_org] == "smmm"


async def test_a_session_of_someone_else_does_not_prove_the_invited_account(client):
    _, client_org, _ = await kullanici(client, "musteri@example.com", role="owner")
    await kullanici(client, "musavir@example.com", role="owner")
    other, _, _ = await kullanici(client, "baska@example.com", role="owner")
    token = await invite_for(client, client_org, "musavir@example.com", "smmm")
    r = await client.post(f"{P}/org/invite/accept", json={"token": token}, headers=other)
    assert r.status_code == 401


async def test_a_person_without_an_account_creates_one_and_lands_in_the_company(client):
    _, org, _ = await kullanici(client, "musteri@example.com", role="owner")
    token = await invite_for(client, org, "yeni@example.com", "analyst")
    short = await client.post(f"{P}/org/invite/accept", json={"token": token})
    assert short.status_code == 422, "a new account needs a password"
    r = await client.post(f"{P}/org/invite/accept", json={"token": token, "password": PAROLA, "full_name": "Yeni Kişi"})
    assert r.status_code == 201, r.text
    user = await user_row(client, "yeni@example.com")
    assert (user.org_id, user.role) == (org, "analyst")
    async with client._maker() as db:
        [joined] = (await db.execute(select(Decision).where(Decision.outcome == "joined"))).scalars().all()
    assert joined.decided_by == user.id and joined.kind == "member_change"


async def test_a_person_with_an_account_but_no_company_starts_in_the_invited_one(client):
    _, org, _ = await kullanici(client, "musteri@example.com", role="owner")
    await kullanici(client, "serbest@example.com", attach_org=False, role="analyst")
    token = await invite_for(client, org, "serbest@example.com", "cfo")
    assert (await client.post(f"{P}/org/invite/accept", json={"token": token, "password": PAROLA})).status_code == 201
    user = await user_row(client, "serbest@example.com")
    assert (user.org_id, user.role) == (org, "cfo")


async def test_the_preview_says_what_the_invitation_is_and_what_state_it_is_in(client):
    _, org, _ = await kullanici(client, "musteri@example.com", role="owner")
    await kullanici(client, "musavir@example.com", role="owner")
    good = await invite_for(client, org, "musavir@example.com", "smmm", token="a" * 64)
    old = await invite_for(client, org, "eski@example.com", "viewer", token="b" * 64, expires=timedelta(days=-1))
    used = await invite_for(client, org, "kullanilmis@example.com", "viewer", token="c" * 64, accepted=True)

    def get(token):
        return client.post(f"{P}/org/invite/preview", json={"token": token})

    valid = (await get(good)).json()["data"]
    assert valid["state"] == "valid" and valid["role"] == "smmm" and valid["email"] == "musavir@example.com"
    assert valid["account_exists"] is True and valid["org_name"] == "musteri@example.com"
    assert (await get(old)).json()["data"]["state"] == "expired"
    assert (await get(used)).json()["data"]["state"] == "used"
    unknown = (await get("d" * 64)).json()["data"]
    assert unknown == {"state": "unknown"}, "nothing else is said about a token that matches nothing"
    new_person = await invite_for(client, org, "hic-yok@example.com", "viewer", token="e" * 64)
    assert (await get(new_person)).json()["data"]["account_exists"] is False


async def test_a_used_or_expired_invitation_is_refused_with_its_own_sentence(client):
    _, org, _ = await kullanici(client, "musteri@example.com", role="owner")
    used = await invite_for(client, org, "a@example.com", "viewer", token="u" * 64, accepted=True)
    old = await invite_for(client, org, "b@example.com", "viewer", token="v" * 64, expires=timedelta(days=-1))
    r_used = await client.post(f"{P}/org/invite/accept", json={"token": used, "password": PAROLA})
    r_old = await client.post(f"{P}/org/invite/accept", json={"token": old, "password": PAROLA})
    assert r_used.status_code == r_old.status_code == 400
    assert r_used.json()["error"] != r_old.json()["error"]


async def test_accepting_the_same_invitation_twice_is_refused_the_second_time(client):
    _, org, _ = await kullanici(client, "musteri@example.com", role="owner")
    token = await invite_for(client, org, "yeni@example.com", "viewer")
    assert (await client.post(f"{P}/org/invite/accept", json={"token": token, "password": PAROLA})).status_code == 201
    assert (await client.post(f"{P}/org/invite/accept", json={"token": token, "password": PAROLA})).status_code == 400

