"""Follow-ups to the write-role guards: membership removal, invite roles, the
member list, platform-operator routes, and who may regenerate the morning brief.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models.organization import Organization, OrgInvite, OrgMembership
from app.models.user import User
from app.services.secret_tokens import hash_token
from tests.api_helpers import PAROLA, bellek_istemcisi, kullanici
from tests.test_route_authorisation import _company

P = "/api/v1"


@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


async def _user_id(client, email: str) -> str:
    async with client._maker() as db:
        return (await db.execute(select(User.id).where(User.email == email))).scalar_one()


async def _memberships(client, user_id: str) -> list[str]:
    async with client._maker() as db:
        rows = await db.execute(select(OrgMembership.org_id).where(OrgMembership.user_id == user_id))
        return [r[0] for r in rows]


# -- 2. removal deletes the membership ----------------------------------------

@pytest.mark.asyncio
async def test_a_removed_member_cannot_switch_back_in(client) -> None:
    org_id, heads = await _company(client, "acme", roles=("owner", "analyst"))
    uid = await _user_id(client, "u-analyst@acme.com")
    r = await client.delete(f"{P}/org/members/{uid}", headers=heads["owner"])
    assert r.status_code == 200, r.text
    assert await _memberships(client, uid) == []
    r = await client.post(f"{P}/org/switch", headers=heads["analyst"], json={"org_id": org_id})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_a_company_whose_accountant_left_can_close_its_month_again(client) -> None:
    _, heads = await _company(client, "beta", roles=("owner", "smmm"))
    close = {"donem": "2026-01"}
    assert (await client.post(f"{P}/smmm/donem-kilitleri", headers=heads["owner"], json=close)).status_code == 403
    uid = await _user_id(client, "u-smmm@beta.com")
    assert (await client.delete(f"{P}/org/members/{uid}", headers=heads["owner"])).status_code == 200
    assert (await client.post(f"{P}/smmm/donem-kilitleri", headers=heads["owner"], json=close)).status_code != 403


@pytest.mark.asyncio
async def test_an_accountant_acting_in_another_client_can_still_be_removed(client) -> None:
    _, heads = await _company(client, "gama", roles=("owner", "smmm"))
    uid = await _user_id(client, "u-smmm@gama.com")
    async with client._maker() as db:
        other = Organization(name="other", slug="other")
        db.add(other)
        await db.flush()
        db.add(OrgMembership(user_id=uid, org_id=other.id, role="smmm"))
        (await db.get(User, uid)).org_id = other.id  # acting elsewhere
        other_id = other.id
        await db.commit()
    assert (await client.delete(f"{P}/org/members/{uid}", headers=heads["owner"])).status_code == 200
    assert await _memberships(client, uid) == [other_id]
    async with client._maker() as db:
        assert (await db.get(User, uid)).org_id == other_id  # untouched: still acting there


@pytest.mark.asyncio
async def test_a_removed_member_falls_back_to_another_organisation_they_belong_to(client) -> None:
    _, heads = await _company(client, "delta", roles=("owner", "analyst"))
    uid = await _user_id(client, "u-analyst@delta.com")
    async with client._maker() as db:
        home = Organization(name="home", slug="home")
        db.add(home)
        await db.flush()
        db.add(OrgMembership(user_id=uid, org_id=home.id, role="owner"))
        home_id = home.id
        await db.commit()
    await client.delete(f"{P}/org/members/{uid}", headers=heads["owner"])
    async with client._maker() as db:
        user = await db.get(User, uid)
        assert user.org_id == home_id and str(user.role) == "owner"


@pytest.mark.asyncio
async def test_dropping_a_client_ends_the_accountants_access(client) -> None:
    h, home, uid = await kullanici(client, "muhasebeci@x.com", role="owner")
    async with client._maker() as db:
        (await db.get(Organization, home)).regional_packs = ["tr"]
        await db.commit()
    await client.post(f"{P}/smmm/register", json={"firma_adi": "Müşavirlik"}, headers=h)
    c = (await client.post(f"{P}/smmm/clients", json={"firma_adi": "Kaya"}, headers=h)).json()["data"]["client"]
    assert (await client.post(f"{P}/org/switch", headers=h, json={"org_id": c["client_org_id"]})).status_code == 200
    r = await client.delete(f"{P}/smmm/clients/{c['id']}", headers=h)
    assert r.status_code == 200, r.text
    assert c["client_org_id"] not in await _memberships(client, uid)
    async with client._maker() as db:
        assert (await db.get(User, uid)).org_id == home  # moved back home
    r = await client.post(f"{P}/org/switch", headers=h, json={"org_id": c["client_org_id"]})
    assert r.status_code == 404


# -- 3. invite roles -----------------------------------------------------------

@pytest.mark.asyncio
async def test_invite_role_is_validated_and_bounded_by_the_inviter(client) -> None:
    _, heads = await _company(client, "eps", roles=("owner", "admin"))

    def invite(who, email, role):
        return client.post(f"{P}/org/invite", headers=heads[who], json={"email": email, "role": role})

    assert (await invite("owner", "a@x.com", "superuser")).status_code == 422
    assert (await invite("admin", "b@x.com", "owner")).status_code == 403
    assert (await invite("admin", "c@x.com", "admin")).status_code == 403
    for role in ("analyst", "viewer", "cfo", "smmm"):
        assert (await invite("admin", f"{role}@x.com", role)).status_code == 201, role
    assert (await invite("owner", "d@x.com", "admin")).status_code == 201
    async with client._maker() as db:
        stored = {i.email: i.role for i in (await db.execute(select(OrgInvite))).scalars()}
    assert "b@x.com" not in stored and stored["d@x.com"] == "admin"


@pytest.mark.asyncio
async def test_an_invite_with_a_stored_junk_role_is_refused_not_500(client) -> None:
    org_id, _ = await _company(client, "zeta", roles=())
    async with client._maker() as db:
        db.add(OrgInvite(org_id=org_id, email="j@x.com", role="superuser", token_hash=hash_token("t" * 64),
                         expires_at=datetime.now(UTC) + timedelta(days=1)))
        await db.commit()
    r = await client.post(f"{P}/org/invite/accept", json={"token": "t" * 64, "password": PAROLA})
    assert r.status_code == 400


# -- 4. member list by membership ---------------------------------------------

@pytest.mark.asyncio
async def test_member_list_shows_an_accountant_acting_elsewhere_with_this_orgs_role(client) -> None:
    _, heads = await _company(client, "eta", roles=("owner", "smmm"))
    uid = await _user_id(client, "u-smmm@eta.com")
    async with client._maker() as db:
        other = Organization(name="other", slug="other")
        db.add(other)
        await db.flush()
        user = await db.get(User, uid)
        user.org_id, user.role = other.id, "owner"  # owner at home, acting in another company
        await db.commit()
    members = (await client.get(f"{P}/org/members", headers=heads["owner"])).json()["data"]["members"]
    by_email = {m["email"]: m["role"] for m in members}
    assert by_email["u-smmm@eta.com"] == "smmm"  # this organisation's role, not users.role
    assert by_email["u-owner@eta.com"] == "owner"
    me = (await client.get(f"{P}/org/me", headers=heads["owner"])).json()["data"]
    assert me["member_count"] == 2


# -- 5. platform operators ----------------------------------------------------

@pytest.mark.asyncio
async def test_pilot_administration_is_for_platform_operators_only(client, monkeypatch) -> None:
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "platform_operator_emails", "")
    owner, _, _ = await kullanici(client, "boss@acme.com", role="owner")
    routes = [("POST", "/pilot/invite/generate", {}), ("GET", "/pilot/invites", None),
              ("DELETE", "/pilot/invite/x", None), ("GET", "/pilot/feedback", None),
              ("GET", "/pilot/feedback/summary", None)]
    for method, path, body in routes:  # empty list: nobody, not even a company owner
        r = await client.request(method, P + path, headers=owner, json=body)
        assert r.status_code == 403, (path, r.status_code)

    monkeypatch.setattr(settings, "platform_operator_emails", " Ops@Tiphys.io , other@x.com")
    ops, _, _ = await kullanici(client, "ops@tiphys.io", role="analyst")
    invite = {"email": "owner@newco.com", "company_name": "Yeni Şirket"}
    assert (await client.post(f"{P}/pilot/invite/generate", headers=ops, json=invite)).status_code == 201
    assert (await client.get(f"{P}/pilot/invites", headers=ops)).status_code == 200
    assert (await client.get(f"{P}/pilot/feedback", headers=ops)).status_code == 200
    # still refused for the company owner
    assert (await client.post(f"{P}/pilot/invite/generate", headers=owner, json=invite)).status_code == 403


# -- 6. the morning brief -----------------------------------------------------

@pytest.mark.asyncio
async def test_regenerating_the_shared_morning_brief_needs_a_writer(client) -> None:
    _, heads = await _company(client, "theta", roles=("viewer", "analyst"))
    for role in ("viewer", "analyst"):
        r = await client.post(f"{P}/brief/morning/generate", headers=heads[role])
        assert r.status_code == 403, role


# -- 1. the analyst keeps their documented power, and no more -----------------

@pytest.mark.asyncio
async def test_an_analyst_may_bring_data_in_but_not_decide(client) -> None:
    _, heads = await _company(client, "iota", roles=("analyst", "viewer"))
    a, v = heads["analyst"], heads["viewer"]
    for path in ("/upload", "/analyze/nope", "/analysis/nope/rerun", "/datasource/nope/sales/csv"):
        assert (await client.post(P + path, headers=a)).status_code != 403, path
        assert (await client.post(P + path, headers=v)).status_code == 403, path
    for method, path, body in [
        ("PATCH", "/transactions/nope/category", {"category": "rent"}),
        ("POST", "/ledger/rows/nope/resolve", {"action": "keep"}),
        ("POST", "/analysis/nope/approve", None),
        ("POST", "/actions/nope/approve", None),
        ("POST", "/smmm/donem-kilitleri", {"donem": "2026-01"}),
        ("POST", "/erp/logo-tiger/connect", {}),
        ("POST", "/org/invite", {"email": "n@x.com", "role": "viewer"}),
        ("DELETE", "/org/members/nope", None),
    ]:
        r = await client.request(method, P + path, headers=a, json=body)
        assert r.status_code == 403, (path, r.status_code)


def test_the_contributor_class_is_the_writer_class_plus_analyst() -> None:
    from app.api.access import CONTRIBUTOR_ROLES, DECIDER_ROLES, WRITER_ROLES

    assert WRITER_ROLES | {"analyst"} == CONTRIBUTOR_ROLES
    assert DECIDER_ROLES < WRITER_ROLES  # a decider is always a writer; cfo is a writer only
