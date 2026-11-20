"""The accountant can see what the agent learned from them, and take it back.

A wrong rule used to be switched off only by two contrary corrections. Now there
is a list (what was learned, how often, whether it is in force) and a way to
delete one. Only a role that may decide an entry may delete; every member of the
organisation may read; one organisation never sees or touches another's.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models.organization import Organization
from app.models.smmm_hesap_kurali import SMMMHesapKurali
from app.services.accounting.ogrenilmis_kural import kurallari_yukle, ogren
from tests.api_helpers import kullanici

P = "/api/v1/smmm/kurallar"


async def _org(client, email, role="owner"):
    h, org, _uid = await kullanici(client, email, role=role)
    async with client._maker() as db:
        (await db.get(Organization, org)).regional_packs = ["tr"]
        await db.commit()
    return h, org


async def _teach(client, org, desc, code, times):
    async with client._maker() as db:
        for _ in range(times):
            await ogren(db, org, desc, None, code)
        await db.commit()


@pytest.mark.asyncio
async def test_the_list_says_what_is_in_force_and_what_is_not_yet(client):
    h, org = await _org(client, "a@x.com")
    await _teach(client, org, "Reklam gideri Meta", "760", 2)   # a rule
    await _teach(client, org, "Kargo gideri Yurtici", "760", 1)  # one correction: not yet
    r = await client.get(P, headers=h)
    assert r.status_code == 200, r.text
    rows = {x["anahtar"]: x for x in r.json()["data"]["kurallar"]}
    reklam = next(v for k, v in rows.items() if "reklam" in k)
    kargo = next(v for k, v in rows.items() if "kargo" in k)
    assert reklam["aktif"] is True and reklam["onay_sayisi"] == 2 and reklam["hesap_kodu"] == "760"
    assert kargo["aktif"] is False and kargo["onay_sayisi"] == 1
    assert reklam["id"] and "anahtar" in reklam


@pytest.mark.asyncio
async def test_a_conflicted_key_shows_no_rule_in_force(client):
    h, org = await _org(client, "b@x.com")
    await _teach(client, org, "Danışmanlık hizmeti Demir", "770", 2)
    await _teach(client, org, "Danışmanlık hizmeti Demir", "750", 2)
    rows = (await client.get(P, headers=h)).json()["data"]["kurallar"]
    assert len(rows) == 2 and not any(x["aktif"] for x in rows)


@pytest.mark.asyncio
async def test_an_organisation_sees_only_its_own_rules(client):
    ha, a = await _org(client, "c@x.com")
    hb, _b = await _org(client, "d@x.com")
    await _teach(client, a, "Reklam gideri Meta", "760", 2)
    assert (await client.get(P, headers=hb)).json()["data"]["kurallar"] == []
    assert len((await client.get(P, headers=ha)).json()["data"]["kurallar"]) == 1


@pytest.mark.asyncio
async def test_deleting_a_rule_takes_it_out_of_force(client):
    h, org = await _org(client, "e@x.com")
    await _teach(client, org, "Reklam gideri Meta", "760", 2)
    rid = (await client.get(P, headers=h)).json()["data"]["kurallar"][0]["id"]
    async with client._maker() as db:
        assert len(await kurallari_yukle(db, org)) == 1

    r = await client.delete(f"{P}/{rid}", headers=h)
    assert r.status_code == 200, r.text
    async with client._maker() as db:
        assert await kurallari_yukle(db, org) == {}
        assert (await db.execute(select(SMMMHesapKurali))).scalars().all() == []


@pytest.mark.asyncio
async def test_a_role_that_may_not_decide_may_read_but_not_delete(client):
    h, org = await _org(client, "f@x.com", role="viewer")
    await _teach(client, org, "Reklam gideri Meta", "760", 2)
    assert (await client.get(P, headers=h)).status_code == 200
    rid = (await client.get(P, headers=h)).json()["data"]["kurallar"][0]["id"]
    assert (await client.delete(f"{P}/{rid}", headers=h)).status_code == 403
    async with client._maker() as db:
        assert len(await kurallari_yukle(db, org)) == 1


@pytest.mark.asyncio
async def test_another_organisations_rule_cannot_be_deleted_or_discovered(client):
    ha, a = await _org(client, "g@x.com")
    hb, _b = await _org(client, "h@x.com")
    await _teach(client, a, "Reklam gideri Meta", "760", 2)
    rid = (await client.get(P, headers=ha)).json()["data"]["kurallar"][0]["id"]
    foreign = await client.delete(f"{P}/{rid}", headers=hb)
    nonexistent = await client.delete(f"{P}/does-not-exist", headers=hb)
    assert foreign.status_code == 404 and nonexistent.status_code == 404
    assert foreign.json() == nonexistent.json()  # whether it exists is not B's to learn
    async with client._maker() as db:
        assert len(await kurallari_yukle(db, a)) == 1
