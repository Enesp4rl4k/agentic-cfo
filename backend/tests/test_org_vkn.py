"""SMMM M1: the VKN belongs to the organisation.

An invoice's direction is "did we sell or buy?", decided by comparing the
parties' VKN with *ours*. With one global setting every company but one got
the wrong answer; now each organisation has its own, and a client without one
gets none (its invoices are held), never the accountant's.
"""

from __future__ import annotations

import pytest

from app.agents.data_ingestion import _try_parse_ubl_xml
from app.models.organization import Organization, OrgMembership
from app.parsers.invoice.ubl_tr import UBLTRInvoiceParser
from app.services.org_identity import normalize, vkn_gecerli, vkn_of
from tests.api_helpers import kullanici
from tests.test_parsers.test_ocr_and_invoice import SAMPLE_UBL_TR_XML

P = "/api/v1"


def _vkn(base9: str) -> str:
    """A well-formed VKN: the nine digits plus the official check digit."""
    d = [int(c) for c in base9]
    total = 0
    for i in range(9):
        tmp = (d[i] + (9 - i)) % 10
        p = (tmp * (2 ** (9 - i))) % 9
        if tmp != 0 and p == 0:
            p = 9
        total += p
    return base9 + str((10 - total % 10) % 10)


def test_checksums():
    assert vkn_gecerli("10000000146")  # the well-known valid TCKN test number
    assert not vkn_gecerli("10000000147")
    ok = _vkn("123456789")
    assert vkn_gecerli(ok) and vkn_gecerli(" " + ok[:3] + "." + ok[3:] + " ")
    assert not vkn_gecerli(ok[:-1] + str((int(ok[-1]) + 1) % 10))
    assert not vkn_gecerli("12345") and not vkn_gecerli("") and not vkn_gecerli(None)
    assert normalize("1234 567 890") == "1234567890"


def test_direction_follows_the_organisations_own_vkn():
    parties = UBLTRInvoiceParser.parse_xml(SAMPLE_UBL_TR_XML, own_vkn="")
    seller, buyer = parties.supplier.vkn_tckn, parties.customer.vkn_tckn
    assert seller and buyer and seller != buyer

    as_seller = _try_parse_ubl_xml(SAMPLE_UBL_TR_XML, own_vkn=seller)
    as_buyer = _try_parse_ubl_xml(SAMPLE_UBL_TR_XML, own_vkn=buyer)
    stranger = _try_parse_ubl_xml(SAMPLE_UBL_TR_XML, own_vkn="")
    assert as_seller[0]["type"] == "income"
    assert as_buyer[0]["type"] == "expense"
    # Neither party is us (or we do not know our own number): held, not guessed.
    assert stranger[0]["confidence"] < 0.8


@pytest.mark.asyncio
async def test_vkn_resolution_never_lends_the_global_number_to_a_client(client, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "gib_vkn", _vkn("111111111"))
    own = _vkn("222222222")
    acct = (await kullanici(client, "acct@x.com"))[2]  # before the session below opens
    async with client._maker() as db:
        legacy = Organization(name="Legacy", slug="legacy")
        with_own = Organization(name="Own", slug="own", vkn=own)
        c_empty = Organization(name="ClientEmpty", slug="c-empty")
        c_own = Organization(name="ClientOwn", slug="c-own", vkn=_vkn("333333333"))
        db.add_all([legacy, with_own, c_empty, c_own])
        await db.flush()
        for c in (c_empty, c_own):
            db.add(OrgMembership(user_id=acct, org_id=c.id, role="smmm"))
        await db.commit()

        assert await vkn_of(db, legacy.id) == _vkn("111111111")  # single-company deployment
        assert await vkn_of(db, with_own.id) == own
        assert await vkn_of(db, c_empty.id) == ""  # held, never the accountant's number
        assert await vkn_of(db, c_own.id) == _vkn("333333333")


@pytest.mark.asyncio
async def test_org_settings_reject_a_malformed_vkn_and_store_a_good_one(client):
    h, _org_id, _ = await kullanici(client, "own@x.com", role="owner")
    bad = await client.patch(f"{P}/org/me", json={"vkn": "1234567891"}, headers=h)
    assert bad.status_code == 422  # one digit off: fails the checksum

    good = _vkn("987654321")
    r = await client.patch(
        f"{P}/org/me", json={"vkn": good[:4] + " " + good[4:], "legal_title": " Kaya Gıda A.Ş. "},
        headers=h,
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["vkn"] == good and data["legal_title"] == "Kaya Gıda A.Ş."

    cleared = await client.patch(f"{P}/org/me", json={"vkn": ""}, headers=h)
    assert cleared.json()["data"]["vkn"] is None


@pytest.mark.asyncio
async def test_a_client_added_with_a_good_vergi_no_gets_it_and_a_bad_one_is_left_unset(client):
    h, home, _ = await kullanici(client, "sm@x.com", role="owner")
    async with client._maker() as db:
        (await db.get(Organization, home)).regional_packs = ["tr"]
        await db.commit()
    await client.post(f"{P}/smmm/register", json={"firma_adi": "M"}, headers=h)

    good = _vkn("555555555")
    a = await client.post(f"{P}/smmm/clients", json={"firma_adi": "A", "vergi_no": good}, headers=h)
    b = await client.post(f"{P}/smmm/clients", json={"firma_adi": "B", "vergi_no": "1234567891"}, headers=h)
    async with client._maker() as db:
        org_a = await db.get(Organization, a.json()["data"]["client"]["client_org_id"])
        org_b = await db.get(Organization, b.json()["data"]["client"]["client_org_id"])
    assert org_a.vkn == good
    assert org_b.vkn is None
