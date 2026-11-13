"""SMMM M1: a client is an organisation of its own, and the accountant switches to it.

The rule these tests hold: `users.org_id` (the organisation a user acts in)
changes to an organisation only if the user is a member of it; a stranger gets
the same 404 as for an organisation that does not exist; and no role is gained
beyond the membership's own.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models.organization import Organization, OrgMembership
from app.models.user import User
from tests.api_helpers import kullanici

P = "/api/v1"


async def _org_of(client, user_id):
    async with client._maker() as db:
        u = await db.get(User, user_id)
        return u.org_id, u.role


@pytest.mark.asyncio
async def test_non_member_cannot_switch_and_cannot_tell_if_org_exists(client):
    a, a_org, a_id = await kullanici(client, "a@x.com")
    _, b_org, _ = await kullanici(client, "b@x.com")

    r = await client.post(f"{P}/org/switch", json={"org_id": b_org}, headers=a)
    assert r.status_code == 404
    r2 = await client.post(f"{P}/org/switch", json={"org_id": "does-not-exist"}, headers=a)
    assert r2.status_code == 404
    assert r.json() == r2.json()
    assert (await _org_of(client, a_id))[0] == a_org


@pytest.mark.asyncio
async def test_add_client_creates_an_org_and_the_accountant_can_switch_both_ways(client):
    h, home_org, uid = await kullanici(client, "smmm@x.com", role="owner")
    # TR pack on the home org, as the SMMM portal requires it.
    async with client._maker() as db:
        org = await db.get(Organization, home_org)
        org.regional_packs = ["tr"]
        await db.commit()
    reg = await client.post(f"{P}/smmm/register", json={"firma_adi": "Mali Müşavirlik"}, headers=h)
    assert reg.status_code in (200, 201), reg.text

    add = await client.post(f"{P}/smmm/clients", json={"firma_adi": "Kaya Gıda"}, headers=h)
    assert add.status_code == 200, add.text
    client_org = add.json()["data"]["client"]["client_org_id"]
    assert client_org and client_org != home_org

    # The client org is Turkish, and the accountant is `smmm` in it.
    async with client._maker() as db:
        c = await db.get(Organization, client_org)
        assert c.country_code == "TR" and c.regional_packs == ["tr"]
        roles = {
            m.org_id: m.role
            for m in (
                await db.execute(select(OrgMembership).where(OrgMembership.user_id == uid))
            ).scalars()
        }
    assert roles == {client_org: "smmm", home_org: "owner"}

    sw = await client.post(f"{P}/org/switch", json={"org_id": client_org}, headers=h)
    assert sw.status_code == 200, sw.text
    assert await _org_of(client, uid) == (client_org, "smmm")

    # The listing says where the user is and where they can go.
    ms = (await client.get(f"{P}/org/memberships", headers=h)).json()["data"]
    assert ms["active_org_id"] == client_org
    assert {m["org_id"]: m["active"] for m in ms["memberships"]} == {
        client_org: True, home_org: False,
    }

    back = await client.post(f"{P}/org/switch", json={"org_id": home_org}, headers=h)
    assert back.status_code == 200
    assert await _org_of(client, uid) == (home_org, "owner")


@pytest.mark.asyncio
async def test_smmm_role_in_a_client_does_not_open_owner_routes(client):
    h, home_org, _uid = await kullanici(client, "s2@x.com", role="owner")
    async with client._maker() as db:
        org = await db.get(Organization, home_org)
        org.regional_packs = ["tr"]
        await db.commit()
    await client.post(f"{P}/smmm/register", json={"firma_adi": "M"}, headers=h)
    cid = (
        await client.post(f"{P}/smmm/clients", json={"firma_adi": "K"}, headers=h)
    ).json()["data"]["client"]["client_org_id"]
    await client.post(f"{P}/org/switch", json={"org_id": cid}, headers=h)

    # Inviting members is an owner/admin act inside the client; `smmm` is neither.
    r = await client.post(
        f"{P}/org/invite", json={"email": "z@x.com", "role": "viewer"}, headers=h
    )
    assert r.status_code in (403, 404), r.text


@pytest.mark.asyncio
async def test_switching_away_from_a_pre_membership_org_stays_reversible(client):
    # A user created before memberships existed has no row for their own org.
    h, home_org, uid = await kullanici(client, "old@x.com", role="owner")
    async with client._maker() as db:
        other = Organization(name="Other", slug="other-org")
        db.add(other)
        await db.flush()
        db.add(OrgMembership(user_id=uid, org_id=other.id, role="viewer"))
        other_id = other.id
        await db.commit()

    assert (await client.post(f"{P}/org/switch", json={"org_id": other_id}, headers=h)).status_code == 200
    assert await _org_of(client, uid) == (other_id, "viewer")
    # Home was recorded on the way out, so this works and the role comes back.
    assert (await client.post(f"{P}/org/switch", json={"org_id": home_org}, headers=h)).status_code == 200
    assert await _org_of(client, uid) == (home_org, "owner")
