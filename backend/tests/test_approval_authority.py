"""SMMM M1: the authority matrix is read when an entry is decided.

Before this, `required_approvals` was written on the entry and never read, so a
`viewer` could approve an entry the policy reserved for the owner. Rules held
here (owner's decision, 2026-11-13): viewer/analyst never; "owner required" is
the owner alone; "smmm required" is the accountant, or owner/admin/cfo when the
company has no accountant; what one approver cannot satisfy is refused.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.organization import Organization, OrgMembership
from app.models.smmm_onay import OnayDurumu, SMMMOnayKaydi
from app.models.user import User
from app.services.approval_authority import verdict
from tests.api_helpers import kullanici

P = "/api/v1/smmm/onay"
OWNER_REQ = {"required_approvals": [{"role": "owner", "count": 1}]}
SMMM_REQ = {"required_approvals": [{"role": "smmm", "count": 1}]}


# ── the pure table ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("role", ["viewer", "analyst"])
@pytest.mark.parametrize("auth", [OWNER_REQ, SMMM_REQ, None])
@pytest.mark.parametrize("has_smmm", [True, False])
def test_viewer_and_analyst_never_decide(role, auth, has_smmm):
    assert not verdict(role, auth, has_smmm).allowed


@pytest.mark.parametrize("has_smmm", [True, False])
def test_owner_required_is_the_owner_alone(has_smmm):
    assert verdict("owner", OWNER_REQ, has_smmm).allowed
    for other in ("smmm", "admin", "cfo"):
        v = verdict(other, OWNER_REQ, has_smmm)
        assert not v.allowed and "owner" in v.reason


def test_smmm_required_with_an_accountant_is_the_accountant_alone():
    assert verdict("smmm", SMMM_REQ, True).allowed
    for other in ("owner", "admin", "cfo"):
        assert not verdict(other, SMMM_REQ, True).allowed


def test_smmm_required_without_an_accountant_falls_to_the_companys_own_books():
    for role in ("owner", "admin", "cfo", "smmm"):
        assert verdict(role, SMMM_REQ, False).allowed


def test_no_recorded_requirement_is_treated_as_smmm_required():
    assert verdict("smmm", None, True).allowed
    assert not verdict("owner", {}, True).allowed
    assert verdict("owner", {"required_approvals": []}, False).allowed


def test_what_one_approver_cannot_satisfy_is_refused_not_relaxed():
    two_roles = {"required_approvals": [{"role": "owner", "count": 1}, {"role": "smmm", "count": 1}]}
    two_people = {"required_approvals": [{"role": "owner", "count": 2}]}
    for auth in (two_roles, two_people):
        v = verdict("owner", auth, False)
        assert not v.allowed and "çoklu" in v.reason


# ── through the routes ───────────────────────────────────────────────────────

async def _org_with_queue(client, *, role: str, authority: dict | None, with_smmm_member: bool = False):
    h, org_id, uid = await kullanici(client, f"{role}-{id(authority)}@x.com", role=role)
    # Created before the session below opens: SQLite locks on a second writer.
    acct_id = (
        (await kullanici(client, f"acct-{role}@x.com", attach_org=False, role="smmm"))[2]
        if with_smmm_member else None
    )
    async with client._maker() as db:
        (await db.get(Organization, org_id)).regional_packs = ["tr"]
        job = AnalysisJob(
            filename="a.csv", file_path="/a.csv", file_type="csv",
            org_id=org_id, user_id=uid, status=JobStatus.COMPLETED,
        )
        db.add(job)
        await db.flush()
        row = SMMMOnayKaydi(
            job_id=job.id, org_id=org_id, kayit_id="k1",
            orijinal_kayit={"authority": authority} if authority else {},
            durum=OnayDurumu.BEKLIYOR,
        )
        db.add(row)
        if acct_id:
            db.add(OrgMembership(user_id=acct_id, org_id=org_id, role="smmm"))
        await db.commit()
        return h, org_id, row.id


async def _durum(client, row_id):
    async with client._maker() as db:
        return (await db.get(SMMMOnayKaydi, row_id)).durum


@pytest.mark.asyncio
async def test_an_analyst_cannot_approve_and_the_row_stays_pending(client):
    h, _org, row = await _org_with_queue(client, role="analyst", authority=SMMM_REQ)
    r = await client.post(f"{P}/{row}/onayla", json={}, headers=h)
    assert r.status_code == 403
    assert await _durum(client, row) == OnayDurumu.BEKLIYOR


@pytest.mark.asyncio
@pytest.mark.parametrize("path, body", [
    ("onayla", {}),
    ("duzeltle", {"hesap_kodu": "770", "hesap_adi": "Giderler"}),
    ("reddet", {"neden": "yanlış"}),
])
async def test_every_decision_route_checks_the_role(client, path, body):
    h, _org, row = await _org_with_queue(client, role="viewer", authority=SMMM_REQ)
    assert (await client.post(f"{P}/{row}/{path}", json=body, headers=h)).status_code == 403
    assert await _durum(client, row) == OnayDurumu.BEKLIYOR


@pytest.mark.asyncio
async def test_a_company_without_an_accountant_can_still_clear_its_own_queue(client):
    h, _org, row = await _org_with_queue(client, role="owner", authority=SMMM_REQ)
    r = await client.post(f"{P}/{row}/onayla", json={}, headers=h)
    assert r.status_code == 200, r.text
    assert await _durum(client, row) == OnayDurumu.ONAYLANDI


@pytest.mark.asyncio
async def test_with_an_accountant_on_board_the_owner_cannot_approve_an_smmm_entry(client):
    h, _org, row = await _org_with_queue(
        client, role="owner", authority=SMMM_REQ, with_smmm_member=True
    )
    r = await client.post(f"{P}/{row}/onayla", json={}, headers=h)
    assert r.status_code == 403 and "smmm" in r.json()["error"]
    assert await _durum(client, row) == OnayDurumu.BEKLIYOR


@pytest.mark.asyncio
async def test_the_accountant_approves_in_the_client_org_and_an_owner_entry_stays_with_the_owner(client):
    # The accountant acts in the client as `smmm`.
    h, org_id, row = await _org_with_queue(client, role="owner", authority=SMMM_REQ, with_smmm_member=True)
    async with client._maker() as db:
        acct = (
            await db.execute(select(User).where(User.email == "acct-owner@x.com"))
        ).scalar_one()
        acct.org_id = org_id
        owner_entry = SMMMOnayKaydi(
            job_id=(await db.get(SMMMOnayKaydi, row)).job_id, org_id=org_id, kayit_id="k2",
            orijinal_kayit={"authority": OWNER_REQ}, durum=OnayDurumu.BEKLIYOR,
        )
        db.add(owner_entry)
        await db.commit()
        owner_row = owner_entry.id
    from tests.api_helpers import PAROLA

    tok = (await client.post("/api/v1/auth/login", json={"email": "acct-owner@x.com", "password": PAROLA})).json()["data"]["access_token"]
    ha = {"Authorization": f"Bearer {tok}"}

    assert (await client.post(f"{P}/{row}/onayla", json={}, headers=ha)).status_code == 200
    denied = await client.post(f"{P}/{owner_row}/onayla", json={}, headers=ha)
    assert denied.status_code == 403 and "owner" in denied.json()["error"]
    # …and the owner can do what the accountant cannot.
    assert (await client.post(f"{P}/{owner_row}/onayla", json={}, headers=h)).status_code == 200


@pytest.mark.asyncio
async def test_bulk_approval_only_approves_what_the_role_may_decide(client):
    h, org_id, smmm_row = await _org_with_queue(client, role="owner", authority=SMMM_REQ)
    async with client._maker() as db:
        job_id = (await db.get(SMMMOnayKaydi, smmm_row)).job_id
        owner_entry = SMMMOnayKaydi(
            job_id=job_id, org_id=org_id, kayit_id="k2",
            orijinal_kayit={"authority": OWNER_REQ}, durum=OnayDurumu.BEKLIYOR,
        )
        db.add(owner_entry)
        await db.commit()
        owner_row = owner_entry.id
    # The company has no accountant, so the owner may decide both.
    r = await client.post(f"{P}/toplu-onayla", json={"kayit_idler": [smmm_row, owner_row]}, headers=h)
    assert r.json()["data"]["onaylandi_count"] == 2 and r.json()["data"]["yetkisiz"] == 0

    h2, _org2, row_a = await _org_with_queue(client, role="analyst", authority=SMMM_REQ)
    r2 = await client.post(f"{P}/toplu-onayla", json={"kayit_idler": [row_a]}, headers=h2)
    d = r2.json()["data"]
    assert d["onaylandi_count"] == 0 and d["yetkisiz"] == 1
    assert await _durum(client, row_a) == OnayDurumu.BEKLIYOR


@pytest.mark.asyncio
async def test_the_queue_tells_the_page_what_this_role_may_decide_and_why_not(client):
    h, _org, row = await _org_with_queue(client, role="analyst", authority=OWNER_REQ)
    item = (await client.get(f"{P}/queue", headers=h)).json()["data"]["kayitlar"][0]
    assert item["id"] == row
    assert item["karar_verebilir"] is False and "rol" in item["karar_engeli"]

    # An admin is a role that decides, just not this entry: the reason names the owner.
    h3, _org3, _row3 = await _org_with_queue(client, role="admin", authority=OWNER_REQ)
    adm = (await client.get(f"{P}/queue", headers=h3)).json()["data"]["kayitlar"][0]
    assert adm["karar_verebilir"] is False and "owner" in adm["karar_engeli"]

    h2, _org2, _row2 = await _org_with_queue(client, role="owner", authority=OWNER_REQ)
    ok = (await client.get(f"{P}/queue", headers=h2)).json()["data"]["kayitlar"][0]
    assert ok["karar_verebilir"] is True and ok["karar_engeli"] is None
