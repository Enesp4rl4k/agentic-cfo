"""SMMM M4: every client's upcoming deadlines in one list, nearest first.

An accountant's month is a set of deadlines across tens of companies. The tax
calendar existed only per company, inside the Cash Radar, and showed a tax only if
that company had paid it from its bank before, so a new client had an empty
calendar. This lists the statutory deadlines for each of the accountant's clients.

What is and is not claimed:
* dates follow `tax_calendar`'s day rules, which are **not yet checked against
  GİB/SGK's own text** - the response says so (`kurallar_dogrulandi: False`);
* an amount appears only when *that client* has paid that tax from its bank
  before (median of its own payments); otherwise it is empty, never estimated;
* whether a client is liable for a tax at all (employees for SGK, provisional tax)
  is not known here: `gecmiste_odeme_var` tells which ones it has actually paid.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from app.models.canonical_transaction import CanonicalTransaction
from app.models.organization import Organization
from app.services.smmm_takvim import musteri_takvimi
from app.services.tax_calendar import statutory_deadlines
from tests.api_helpers import kullanici

P = "/api/v1"
ANCHOR = date(2026, 2, 2)  # a Monday


def _cash(org, n, day, cents, cp, desc):
    return CanonicalTransaction(
        org_id=org, source_type="t", source_record_id=f"{org}-{n}",
        transaction_date=datetime(*day, tzinfo=UTC), amount_cents=cents, currency="TRY",
        direction="expense", category="x", counterparty=cp, description=desc, confidence=90,
        ledger_status="active", basis="cash",
    )


async def _accountant(client, email):
    h, home, uid = await kullanici(client, email, role="owner")
    async with client._maker() as db:
        (await db.get(Organization, home)).regional_packs = ["tr"]
        await db.commit()
    await client.post(f"{P}/smmm/register", json={"firma_adi": "Müşavirlik"}, headers=h)
    return h, uid


async def _add(client, h, name):
    c = (await client.post(f"{P}/smmm/clients", json={"firma_adi": name}, headers=h)).json()["data"]["client"]
    return c["id"], c["client_org_id"]


def test_statutory_deadlines_are_a_pure_list_and_keep_the_weekend_rule():
    out = statutory_deadlines(ANCHOR, date(2026, 3, 31))
    kdv = [d for d in out if d.kind == "kdv"]
    # 28 Feb 2026 is a Saturday: the deadline moves to Monday 2 March.
    assert date(2026, 3, 2) in [d.due for d in kdv]
    assert all(ANCHOR <= d.due <= date(2026, 3, 31) for d in out)
    assert {d.kind for d in out} >= {"kdv", "muhtasar", "sgk", "gecici_vergi"}


@pytest.mark.asyncio
async def test_every_client_gets_the_deadlines_nearest_first(client):
    h, _uid = await _accountant(client, "t1@x.com")
    a, _ = await _add(client, h, "A Ltd")
    b, _ = await _add(client, h, "B Ltd")
    async with client._maker() as db:
        out = await musteri_takvimi(db, (await _muhasebeci(client, "t1@x.com")), ANCHOR, gun=45)
    rows = out["kalemler"]
    assert {r["musteri_id"] for r in rows} == {a, b}
    assert [r["tarih"] for r in rows] == sorted(r["tarih"] for r in rows)
    assert out["kurallar_dogrulandi"] is False


@pytest.mark.asyncio
async def test_an_amount_comes_only_from_that_clients_own_payments(client):
    h, _uid = await _accountant(client, "t2@x.com")
    a, aorg = await _add(client, h, "A Ltd")
    b, _borg = await _add(client, h, "B Ltd")
    async with client._maker() as db:
        db.add_all([_cash(aorg, i, (2025, m, 28), 120_000, "Vergi Dairesi", "KDV tahakkuk odeme")
                    for i, m in enumerate((10, 11, 12))])
        await db.commit()
        out = await musteri_takvimi(db, await _muhasebeci(client, "t2@x.com"), ANCHOR, gun=45)
    kdv_a = [r for r in out["kalemler"] if r["musteri_id"] == a and r["tur"] == "kdv"]
    kdv_b = [r for r in out["kalemler"] if r["musteri_id"] == b and r["tur"] == "kdv"]
    assert kdv_a and all(r["tutar_kurus"] == 120_000 and r["gecmiste_odeme_var"] for r in kdv_a)
    assert kdv_b and all(r["tutar_kurus"] is None and not r["gecmiste_odeme_var"] for r in kdv_b)


async def _muhasebeci(client, email):
    from sqlalchemy import select

    from app.models.smmm_portal import SMMMMuhasebeci
    from app.models.user import User

    async with client._maker() as db:
        uid = (await db.execute(select(User.id).where(User.email == email))).scalar_one()
        return (await db.execute(select(SMMMMuhasebeci.id).where(SMMMMuhasebeci.user_id == uid))).scalar_one()


# ── through the route ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_route_lists_only_this_accountants_clients(client):
    h1, _ = await _accountant(client, "t3@x.com")
    h2, _ = await _accountant(client, "t4@x.com")
    a, _ = await _add(client, h1, "Mine Ltd")
    await _add(client, h2, "Theirs Ltd")
    r = await client.get(f"{P}/smmm/takvim?gun=45", headers=h1)
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert {x["musteri_id"] for x in d["kalemler"]} == {a}
    assert all(x["firma_adi"] == "Mine Ltd" for x in d["kalemler"])
    assert d["kurallar_dogrulandi"] is False


@pytest.mark.asyncio
async def test_someone_who_is_not_an_accountant_gets_404(client):
    h, _org, _uid = await kullanici(client, "t5@x.com", role="owner")
    assert (await client.get(f"{P}/smmm/takvim", headers=h)).status_code == 404


@pytest.mark.asyncio
async def test_the_window_is_bounded(client):
    h, _ = await _accountant(client, "t6@x.com")
    await _add(client, h, "A Ltd")
    assert (await client.get(f"{P}/smmm/takvim?gun=400", headers=h)).status_code == 422
