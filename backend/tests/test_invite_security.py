"""Adversarial review of the invitation flow and of acting in one of several organisations.

Each test states the attack; a pass means the attack fails.
"""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest_asyncio
from sqlalchemy import select

from app.models.decision import Decision
from app.models.organization import OrgInvite, OrgMembership
from app.models.user import User
from app.services.secret_tokens import hash_token
from tests.api_helpers import PAROLA, bellek_istemcisi, emailed_token, kullanici

P = "/api/v1"


@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


async def add_membership(client, user_id: str, org_id: str, role: str) -> None:
    async with client._maker() as db:
        db.add(OrgMembership(user_id=user_id, org_id=org_id, role=role))
        await db.commit()


async def seed_invite(client, org_id: str, email: str, role: str = "viewer", token: str | None = None) -> str:
    token = token or (email.replace("@", "").replace(".", "") + role).ljust(64, "z")[:64]
    async with client._maker() as db:
        db.add(OrgInvite(org_id=org_id, email=email, role=role, token_hash=hash_token(token), accepted=False,
                         expires_at=datetime.now(UTC) + timedelta(days=7)))
        await db.commit()
    return token


async def users_with_email(client, email: str) -> list[User]:
    async with client._maker() as db:
        rows = (await db.execute(select(User))).scalars().all()
    return [u for u in rows if u.email.lower() == email.lower()]


# ── 1. the token ────────────────────────────────────────────────────────────

async def test_tokens_are_long_random_and_never_handed_back_to_the_inviter(client):
    owner, _org, _ = await kullanici(client, "sahip@example.com", role="owner")
    seen = set()
    for i in range(3):
        r = await client.post(f"{P}/org/invite", headers=owner, json={"email": f"k{i}@example.com", "role": "viewer"})
        assert r.status_code == 201
        assert "token" not in json.dumps(r.json()).lower()
    listing = await client.get(f"{P}/org/invites", headers=owner)
    assert "token" not in json.dumps(listing.json()).lower()
    async with client._maker() as db:
        stored = {i.email: i.token_hash for i in (await db.execute(select(OrgInvite))).scalars().all()}
    for i in range(3):
        email = f"k{i}@example.com"
        token = await emailed_token(client, "org_invite", email)
        assert len(token) == 64 and int(token, 16) >= 0
        assert stored[email] == hash_token(token) != token, "only the digest is stored"
        seen.add(token)
    assert len(seen) == 3


async def test_a_cancelled_invitation_is_dead(client):
    owner, _org, _ = await kullanici(client, "sahip@example.com", role="owner")
    await client.post(f"{P}/org/invite", headers=owner, json={"email": "yeni@example.com", "role": "viewer"})
    async with client._maker() as db:
        invite_id = (await db.execute(select(OrgInvite))).scalar_one().id
    token = await emailed_token(client, "org_invite", "yeni@example.com")
    assert (await client.delete(f"{P}/org/invites/{invite_id}", headers=owner)).status_code == 200
    assert (await client.post(f"{P}/org/invite/preview", json={"token": token})).json()["data"] == {"state": "unknown"}
    r = await client.post(f"{P}/org/invite/accept", json={"token": token, "password": PAROLA})
    assert r.status_code == 400
    assert not await users_with_email(client, "yeni@example.com")


async def test_two_simultaneous_accepts_of_one_token_make_one_winner(client):
    _, org, _ = await kullanici(client, "sahip@example.com", role="owner")
    token = await seed_invite(client, org, "yeni@example.com", "viewer")
    results = await asyncio.gather(
        *[client.post(f"{P}/org/invite/accept", json={"token": token, "password": PAROLA}) for _ in range(2)]
    )
    codes = sorted(r.status_code for r in results)
    assert codes == [201, 400], codes
    assert len(await users_with_email(client, "yeni@example.com")) == 1
    async with client._maker() as db:
        joined = (await db.execute(select(Decision).where(Decision.outcome == "joined"))).scalars().all()
    assert len(joined) == 1


async def test_the_token_is_not_in_the_url_of_any_endpoint(client):
    """A token in a query string lands in access logs of the server and of every proxy in front of it."""
    _, org, _ = await kullanici(client, "sahip@example.com", role="owner")
    token = await seed_invite(client, org, "yeni@example.com", "viewer")
    assert (await client.get(f"{P}/org/invite/preview", params={"token": token})).status_code in (404, 405)
    r = await client.post(f"{P}/org/invite/preview", json={"token": token})
    assert r.status_code == 200 and r.json()["data"]["state"] == "valid"


def test_the_invitation_endpoints_are_rate_limited_like_login():
    from app.middleware.rate_limit import _get_limit

    for path in (f"{P}/org/invite/accept", f"{P}/org/invite/preview"):
        limit, window = _get_limit(path)
        assert limit / window <= 30 / 60, f"{path} allows {limit} per {window}s"


# ── 2. account binding ──────────────────────────────────────────────────────

async def test_another_signed_in_user_cannot_take_an_invitation_addressed_to_someone_else(client):
    _, org, _ = await kullanici(client, "sahip@example.com", role="owner")
    attacker, _, _attacker_id = await kullanici(client, "saldirgan@example.com", role="viewer")
    await kullanici(client, "hedef@example.com", attach_org=False, role="analyst")
    token = await seed_invite(client, org, "hedef@example.com", "admin")
    for body in ({"token": token}, {"token": token, "password": PAROLA + "x"}):
        r = await client.post(f"{P}/org/invite/accept", json=body, headers=attacker)
        assert r.status_code == 401
    async with client._maker() as db:
        assert (await db.execute(select(OrgMembership).where(OrgMembership.org_id == org))).first() is None


async def test_a_case_variant_of_an_existing_address_joins_that_account_and_makes_no_second_one(client):
    _, org, _ = await kullanici(client, "sahip@example.com", role="owner")
    await kullanici(client, "musavir@example.com", role="owner")
    token = await seed_invite(client, org, "Musavir@Example.com", "smmm")
    # The token alone must not create a lookalike account next to the real one.
    r = await client.post(f"{P}/org/invite/accept", json={"token": token, "password": "Baska-Sifre-123"})
    assert r.status_code == 401
    assert len(await users_with_email(client, "musavir@example.com")) == 1
    ok = await client.post(f"{P}/org/invite/accept", json={"token": token, "password": PAROLA})
    assert ok.status_code == 201, ok.text
    assert len(await users_with_email(client, "musavir@example.com")) == 1


async def test_whitespace_and_case_in_a_new_address_are_normalised_once(client):
    owner, _org, _ = await kullanici(client, "sahip@example.com", role="owner")
    r = await client.post(f"{P}/org/invite", headers=owner, json={"email": "Yeni.Kisi@Example.com", "role": "viewer"})
    assert r.status_code == 201
    # Re-inviting a case variant replaces the pending one instead of leaving two live tokens.
    await client.post(f"{P}/org/invite", headers=owner, json={"email": "yeni.kisi@example.com", "role": "viewer"})
    async with client._maker() as db:
        pending = (await db.execute(select(OrgInvite).where(OrgInvite.accepted.is_(False)))).scalars().all()
    assert len(pending) == 1


async def test_a_deactivated_account_is_not_signed_in_by_an_invitation(client):
    _, org, _ = await kullanici(client, "sahip@example.com", role="owner")
    _, _, uid = await kullanici(client, "eski@example.com", role="owner")
    async with client._maker() as db:
        (await db.get(User, uid)).is_active = False
        await db.commit()
    token = await seed_invite(client, org, "eski@example.com", "viewer")
    r = await client.post(f"{P}/org/invite/accept", json={"token": token, "password": PAROLA})
    assert r.status_code == 403 and "access_token" not in r.text


async def test_the_password_policy_on_accept_is_the_sign_up_policy(client):
    _, org, _ = await kullanici(client, "sahip@example.com", role="owner")
    token = await seed_invite(client, org, "yeni@example.com", "viewer")
    assert (await client.post(f"{P}/org/invite/accept", json={"token": token, "password": "short"})).status_code == 422
    assert (await client.post(f"{P}/org/invite/accept", json={"token": token, "password": PAROLA})).status_code == 201
    # The stored hash verifies through the login route: same hashing as sign-up.
    login = await client.post(f"{P}/auth/login", json={"email": "yeni@example.com", "password": PAROLA})
    assert login.status_code == 200


# ── 3. privilege ────────────────────────────────────────────────────────────

async def test_an_admin_cannot_mint_an_owner_or_admin_by_posting_the_role(client):
    admin, _org, _ = await kullanici(client, "yonetici@example.com", role="admin")
    for role in ("owner", "admin"):
        r = await client.post(f"{P}/org/invite", headers=admin, json={"email": f"{role}@example.com", "role": role})
        assert r.status_code == 403, role
    for role in ("cfo", "smmm", "analyst", "viewer"):
        r = await client.post(f"{P}/org/invite", headers=admin, json={"email": f"{role}@example.com", "role": role})
        assert r.status_code == 201, role


async def test_below_admin_cannot_invite_at_all(client):
    for role in ("cfo", "smmm", "analyst", "viewer"):
        headers, _, _ = await kullanici(client, f"{role}@example.com", role=role)
        r = await client.post(f"{P}/org/invite", headers=headers, json={"email": f"x{role}@example.com", "role": "viewer"})
        assert r.status_code == 403, role


async def test_the_accept_body_cannot_retarget_organisation_or_role(client):
    _, org, _ = await kullanici(client, "sahip@example.com", role="owner")
    _, other_org, _ = await kullanici(client, "baska@example.com", role="owner")
    token = await seed_invite(client, org, "yeni@example.com", "viewer")
    r = await client.post(f"{P}/org/invite/accept", json={
        "token": token, "password": PAROLA, "org_id": other_org, "role": "owner", "email": "baska@example.com",
    })
    assert r.status_code == 201
    user = (await users_with_email(client, "yeni@example.com"))[0]
    assert (user.org_id, user.role) == (org, "viewer")
    async with client._maker() as db:
        rows = (await db.execute(select(OrgMembership).where(OrgMembership.user_id == user.id))).scalars().all()
    assert [(m.org_id, m.role) for m in rows] == [(org, "viewer")]


async def test_an_admin_cannot_remove_an_owner(client):
    admin, org, _ = await kullanici(client, "yonetici@example.com", role="admin")
    async with client._maker() as db:
        owner = User(email="sahip@example.com", hashed_password="x", role="owner", org_id=org)
        db.add(owner)
        await db.flush()
        owner_id = owner.id
        db.add(OrgMembership(user_id=owner_id, org_id=org, role="owner"))
        await db.commit()
    r = await client.delete(f"{P}/org/members/{owner_id}", headers=admin)
    assert r.status_code == 403


# ── 4. several memberships: the role and the data are those of the company being acted in ──

async def viewer_in_a_owner_in_b(client):
    headers, a, uid = await kullanici(client, "cok@example.com", role="viewer")
    _, b, _ = await kullanici(client, "b-sahip@example.com", role="owner")
    await add_membership(client, uid, a, "viewer")
    await add_membership(client, uid, b, "owner")
    return headers, a, b, uid


async def test_the_owner_role_of_b_does_not_work_inside_a(client):
    headers, a, _b, _ = await viewer_in_a_owner_in_b(client)
    assert (await client.post(f"{P}/org/invite", headers=headers, json={"email": "x@example.com", "role": "viewer"})).status_code == 403
    assert (await client.patch(f"{P}/org/me", headers=headers, json={"name": "ele geçirildi"})).status_code == 403
    assert (await client.post(f"{P}/actions/nope/approve", headers=headers)).status_code == 403
    assert (await client.get(f"{P}/org/me", headers=headers)).json()["data"]["org_id"] == a


async def test_the_client_cannot_name_the_acting_organisation(client):
    headers, a, b, _ = await viewer_in_a_owner_in_b(client)
    for extra in ({"X-Org-Id": b}, {"X-Organization-Id": b}, {"X-Tenant-Id": b}):
        r = await client.get(f"{P}/org/me", headers={**headers, **extra})
        assert r.json()["data"]["org_id"] == a
    r = await client.get(f"{P}/org/me", headers=headers, params={"org_id": b})
    assert r.json()["data"]["org_id"] == a


async def test_switching_to_an_organisation_without_a_membership_is_refused(client):
    headers, a, _b, _ = await viewer_in_a_owner_in_b(client)
    _, stranger_org, _ = await kullanici(client, "yabanci@example.com", role="owner")
    assert (await client.post(f"{P}/org/switch", headers=headers, json={"org_id": stranger_org})).status_code == 404
    assert (await client.get(f"{P}/org/me", headers=headers)).json()["data"]["org_id"] == a


async def test_switching_swaps_role_and_data_together(client):
    headers, a, b, _ = await viewer_in_a_owner_in_b(client)
    assert (await client.post(f"{P}/org/switch", headers=headers, json={"org_id": b})).status_code == 200
    assert (await client.post(f"{P}/org/invite", headers=headers, json={"email": "x@example.com", "role": "viewer"})).status_code == 201
    pending = (await client.get(f"{P}/org/invites", headers=headers)).json()["data"]
    assert [i["email"] for i in pending] == ["x@example.com"]
    assert (await client.post(f"{P}/org/switch", headers=headers, json={"org_id": a})).status_code == 200
    assert (await client.get(f"{P}/org/invites", headers=headers)).status_code == 403  # viewer in A: no list of B's invites
    assert (await client.post(f"{P}/org/invite", headers=headers, json={"email": "y@example.com", "role": "viewer"})).status_code == 403


async def test_removal_cuts_the_session_that_is_already_open(client):
    headers, a, b, uid = await viewer_in_a_owner_in_b(client)
    assert (await client.post(f"{P}/org/switch", headers=headers, json={"org_id": b})).status_code == 200
    assert (await client.get(f"{P}/org/members", headers=headers)).status_code == 200  # warm any cache
    boss = await client.post(f"{P}/auth/login", json={"email": "b-sahip@example.com", "password": PAROLA})
    boss_headers = {"Authorization": f"Bearer {boss.json()['data']['access_token']}"}
    assert (await client.delete(f"{P}/org/members/{uid}", headers=boss_headers)).status_code == 200
    me = (await client.get(f"{P}/org/me", headers=headers)).json()["data"]
    assert me["org_id"] == a, "the same bearer token now acts in the company they still belong to"
    assert (await client.post(f"{P}/org/invite", headers=headers, json={"email": "z@example.com", "role": "viewer"})).status_code == 403
    assert (await client.post(f"{P}/org/switch", headers=headers, json={"org_id": b})).status_code == 404


# ── 5. decision records ────────────────────────────────────────────────────

async def test_member_decisions_name_the_right_actor_and_organisation_and_hold_no_secret(client):
    headers, a, b, uid = await viewer_in_a_owner_in_b(client)
    await client.post(f"{P}/org/switch", headers=headers, json={"org_id": b})
    await client.post(f"{P}/org/invite", headers=headers, json={"email": "yeni@example.com", "role": "viewer"})
    async with client._maker() as db:
        assert (await db.execute(select(OrgInvite))).scalar_one()
    token = await emailed_token(client, "org_invite", "yeni@example.com")
    await client.post(f"{P}/org/invite", headers=headers, json={"email": "iptal@example.com", "role": "viewer"})
    async with client._maker() as db:
        cancel_id = (await db.execute(select(OrgInvite.id).where(OrgInvite.email == "iptal@example.com"))).scalar_one()
    await client.delete(f"{P}/org/invites/{cancel_id}", headers=headers)
    await client.post(f"{P}/org/invite/accept", json={"token": token, "password": PAROLA})
    async with client._maker() as db:
        rows = (await db.execute(select(Decision))).scalars().all()
    outcomes = {r.outcome for r in rows}
    assert {"invited", "invite_cancelled", "joined"} <= outcomes
    for r in rows:
        assert r.org_id == b and r.org_id != a
        blob = json.dumps({k: str(v) for k, v in vars(r).items() if not k.startswith("_")})
        assert token not in blob and PAROLA not in blob
    invited = next(r for r in rows if r.outcome == "invited")
    assert invited.decided_by == uid


# ── live sockets follow the membership ──────────────────────────────────────

async def test_a_socket_opened_in_a_company_is_closed_when_the_person_leaves_it(client, monkeypatch):
    from app.api import ws_auth

    monkeypatch.setattr(ws_auth, "session_factory", lambda: client._maker)

    headers, a, b, uid = await viewer_in_a_owner_in_b(client)
    await client.post(f"{P}/org/switch", headers=headers, json={"org_id": b})
    assert await ws_auth.still_acting_in(uid, b) is True
    await client.post(f"{P}/org/switch", headers=headers, json={"org_id": a})
    assert await ws_auth.still_acting_in(uid, b) is False, "switched away: the socket for B must close"
    assert await ws_auth.still_acting_in(uid, a) is True
    boss = await client.post(f"{P}/auth/login", json={"email": "b-sahip@example.com", "password": PAROLA})
    boss_headers = {"Authorization": f"Bearer {boss.json()['data']['access_token']}"}
    await client.post(f"{P}/org/switch", headers=headers, json={"org_id": b})
    await client.delete(f"{P}/org/members/{uid}", headers=boss_headers)
    assert await ws_auth.still_acting_in(uid, b) is False


async def test_a_scheduled_job_is_attributed_to_a_member_not_to_whoever_is_acting_there(client):
    from app.services.scheduled_sync import job_owner_id

    _, org, owner_id = await kullanici(client, "sahip@example.com", role="owner")
    async with client._maker() as db:
        viewer = User(email="v@example.com", hashed_password="x", role="viewer", org_id=org)
        db.add(viewer)
        await db.flush()
        db.add(OrgMembership(user_id=owner_id, org_id=org, role="owner"))
        db.add(OrgMembership(user_id=viewer.id, org_id=org, role="viewer"))
        # The owner is acting in a different company right now.
        owner = await db.get(User, owner_id)
        owner.org_id = None
        await db.commit()
        assert await job_owner_id(db, org) == owner_id


# ── /ws/chat and the user lookup follow the membership on every request ─────

class _Socket:
    """Just enough of a WebSocket for `websocket_chat`."""

    from starlette.websockets import WebSocketState

    def __init__(self, messages):
        self.client_state = self.WebSocketState.CONNECTED
        self.client = None
        self.headers: dict[str, str] = {}
        self._messages = list(messages)
        self.sent: list[str] = []
        self.closed: int | None = None

    async def accept(self):
        return None

    async def receive_text(self):
        from starlette.websockets import WebSocketDisconnect

        if not self._messages:
            raise WebSocketDisconnect()
        item = self._messages.pop(0)
        if callable(item):
            await item()
            return await self.receive_text()
        return item

    async def send_text(self, text):
        self.sent.append(text)

    async def close(self, code=1000):
        self.closed = code
        self.client_state = self.WebSocketState.DISCONNECTED


async def _chat(client, monkeypatch, headers_token: str, steps):
    from app.api import ws_auth, ws_stream

    monkeypatch.setattr(ws_auth, "session_factory", lambda: client._maker)
    asked: list[str | None] = []

    async def fake_prompt(question, job_id, org_id, user):
        asked.append(org_id)
        raise RuntimeError("stop before the model")

    monkeypatch.setattr(ws_stream, "_build_chat_prompt", fake_prompt)
    monkeypatch.setattr("app.services.llm_structured._is_placeholder_key", lambda _k: False)
    ws = _Socket(steps)
    await ws_stream.websocket_chat(ws, token=headers_token)  # type: ignore[arg-type]
    return ws, asked


def _token(headers):
    return headers["Authorization"].split()[1]


async def test_chat_socket_refuses_the_next_message_after_removal(client, monkeypatch):
    headers, _a, b, uid = await viewer_in_a_owner_in_b(client)
    await client.post(f"{P}/org/switch", headers=headers, json={"org_id": b})
    boss = await client.post(f"{P}/auth/login", json={"email": "b-sahip@example.com", "password": PAROLA})
    boss_headers = {"Authorization": f"Bearer {boss.json()['data']['access_token']}"}

    async def remove():
        assert (await client.delete(f"{P}/org/members/{uid}", headers=boss_headers)).status_code == 200

    q = json.dumps({"type": "chat", "question": "ciro?"})
    ws, asked = await _chat(client, monkeypatch, _token(headers), [q, remove, q])
    assert asked == [b], "the first message, before removal, is answered for B"
    assert ws.closed == 1008 and asked.count(b) == 1


async def test_chat_socket_never_answers_about_the_old_company_after_a_switch(client, monkeypatch):
    headers, a, b, _uid = await viewer_in_a_owner_in_b(client)
    await client.post(f"{P}/org/switch", headers=headers, json={"org_id": b})

    async def switch():
        assert (await client.post(f"{P}/org/switch", headers=headers, json={"org_id": a})).status_code == 200

    q = json.dumps({"type": "chat", "question": "ciro?"})
    ws, asked = await _chat(client, monkeypatch, _token(headers), [switch, q])
    assert asked == [] and ws.closed == 1008


async def test_chat_socket_refuses_a_deactivated_user(client, monkeypatch):
    headers, _a, _b, uid = await viewer_in_a_owner_in_b(client)

    async def deactivate():
        async with client._maker() as db:
            (await db.get(User, uid)).is_active = False
            await db.commit()

    q = json.dumps({"type": "chat", "question": "ciro?"})
    ws, asked = await _chat(client, monkeypatch, _token(headers), [deactivate, q])
    assert asked == [] and ws.closed == 1008


async def test_a_second_worker_sees_removal_and_deactivation_at_once(client):
    """Two workers share nothing but the database: nothing about access may live in process memory."""
    import app.api.auth as auth

    assert not hasattr(auth, "_USER_CACHE"), "no per-process user cache"
    headers, a, b, uid = await viewer_in_a_owner_in_b(client)
    await client.post(f"{P}/org/switch", headers=headers, json={"org_id": b})
    assert (await client.get(f"{P}/org/me", headers=headers)).json()["data"]["org_id"] == b  # 'worker 1' warm
    # 'Worker 2' changes the facts straight in the database, as another process would.
    async with client._maker() as db:
        row = (await db.execute(select(OrgMembership).where(OrgMembership.user_id == uid, OrgMembership.org_id == b))).scalar_one()
        await db.delete(row)
        user = await db.get(User, uid)
        user.org_id, user.role = a, "viewer"
        await db.commit()
    assert (await client.get(f"{P}/org/me", headers=headers)).json()["data"]["org_id"] == a
    async with client._maker() as db:
        (await db.get(User, uid)).is_active = False
        await db.commit()
    assert (await client.get(f"{P}/org/me", headers=headers)).status_code == 401


async def test_a_token_with_an_outdated_role_claim_gets_the_membership_role(client):
    from app.services.auth import create_access_token

    _headers, _a, _b, uid = await viewer_in_a_owner_in_b(client)  # viewer in A, acting in A
    forged = create_access_token(uid, "cok@example.com", "owner")  # claim says owner
    h = {"Authorization": f"Bearer {forged}"}
    assert (await client.post(f"{P}/org/invite", headers=h, json={"email": "x@example.com", "role": "viewer"})).status_code == 403
    assert (await client.post(f"{P}/actions/nope/approve", headers=h)).status_code == 403
