"""Plan v10 §O0 — a pilot company sees only the flow it is piloting.

`focus_mode` is an organisation setting the owner or an admin can switch on. It
is off for every existing company and for the demo, so nothing changes for them.
"""
from __future__ import annotations

import pytest_asyncio
from sqlalchemy import select

from app.models.organization import Organization
from tests.api_helpers import bellek_istemcisi, kullanici


@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


async def test_a_company_starts_with_every_screen(client):
    headers, org_id, _ = await kullanici(client, "tam@example.com", role="owner")
    me = (await client.get("/api/v1/org/me", headers=headers)).json()["data"]
    assert me["focus_mode"] is False
    async with client._maker() as db:
        assert (await db.get(Organization, org_id)).focus_mode is False


async def test_an_admin_switches_focus_on_and_off(client):
    headers, _, _ = await kullanici(client, "admin@example.com", role="owner")
    on = await client.patch("/api/v1/org/me", json={"focus_mode": True}, headers=headers)
    assert on.status_code == 200, on.text
    assert on.json()["data"]["focus_mode"] is True
    assert (await client.get("/api/v1/org/me", headers=headers)).json()["data"]["focus_mode"] is True

    off = await client.patch("/api/v1/org/me", json={"focus_mode": False}, headers=headers)
    assert off.json()["data"]["focus_mode"] is False


async def test_leaving_it_out_changes_nothing(client):
    headers, _, _ = await kullanici(client, "ayri@example.com", role="owner")
    await client.patch("/api/v1/org/me", json={"focus_mode": True}, headers=headers)
    other = await client.patch("/api/v1/org/me", json={"locale": "tr-TR"}, headers=headers)
    assert other.json()["data"]["focus_mode"] is True


async def test_an_analyst_cannot_switch_it(client):
    headers, org_id, _ = await kullanici(client, "analist@example.com", role="analyst")
    response = await client.patch("/api/v1/org/me", json={"focus_mode": True}, headers=headers)
    assert response.status_code == 403
    async with client._maker() as db:
        rows = (await db.execute(select(Organization.focus_mode).where(Organization.id == org_id))).scalars().all()
    assert rows == [False]
