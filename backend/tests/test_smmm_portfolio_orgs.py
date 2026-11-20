"""The accountant's portfolio shows clients that are organisations of their own.

M1 made a client its own organisation. The portfolio status was still derived only
from jobs carrying `smmm_client_id`, a link only the old "upload for a client" form
set. An accountant who switches into a client and uploads there creates a job with
`org_id = the client's org` and no `smmm_client_id`, so every such client showed
"veri_yok" forever, with work and pending approvals sitting in it.

What an accountant needs first on a Monday is *which of my clients has something
waiting for me*. That has to be true for a client however its work arrived.
"""

from __future__ import annotations

import pytest

from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.organization import Organization
from app.models.smmm_onay import OnayDurumu, SMMMOnayKaydi
from app.services.smmm_clients import status_for_clients
from tests.api_helpers import kullanici

P = "/api/v1"


async def _accountant(client, email):
    h, home, uid = await kullanici(client, email, role="owner")
    async with client._maker() as db:
        (await db.get(Organization, home)).regional_packs = ["tr"]
        await db.commit()
    await client.post(f"{P}/smmm/register", json={"firma_adi": "Müşavirlik"}, headers=h)
    return h, home, uid


async def _add_client(client, h, name):
    r = await client.post(f"{P}/smmm/clients", json={"firma_adi": name}, headers=h)
    c = r.json()["data"]["client"]
    return c["id"], c["client_org_id"]


async def _job(db, org, uid, *, client_id=None, status=JobStatus.COMPLETED):
    j = AnalysisJob(filename="a.csv", file_path="/a.csv", file_type="csv", org_id=org,
                    user_id=uid, status=status, smmm_client_id=client_id)
    db.add(j)
    await db.flush()
    return j.id


async def _pending(db, job_id, org, n):
    for i in range(n):
        db.add(SMMMOnayKaydi(job_id=job_id, org_id=org, kayit_id=f"{job_id}-{i}",
                             orijinal_kayit={}, durum=OnayDurumu.BEKLIYOR))


@pytest.mark.asyncio
async def test_work_done_inside_the_clients_own_org_is_seen(client):
    h, _home, uid = await _accountant(client, "p1@x.com")
    cid, corg = await _add_client(client, h, "Kaya Gıda")
    async with client._maker() as db:
        await _job(db, corg, uid)  # uploaded after switching into the client: no smmm_client_id
        await db.commit()
        s = (await status_for_clients(db, [cid]))[cid]
    assert s.job_count == 1 and s.stage == "analiz_edildi" and s.last_job_id


@pytest.mark.asyncio
async def test_pending_approvals_are_counted_over_every_job_not_just_the_newest(client):
    h, _home, uid = await _accountant(client, "p2@x.com")
    cid, corg = await _add_client(client, h, "Kaya Gıda")
    async with client._maker() as db:
        old = await _job(db, corg, uid)
        await _pending(db, old, corg, 3)
        await db.flush()
        new = await _job(db, corg, uid)
        await _pending(db, new, corg, 2)
        await db.commit()
        s = (await status_for_clients(db, [cid]))[cid]
    assert s.pending_review == 5 and s.stage == "onay_bekliyor" and s.needs_attention


@pytest.mark.asyncio
async def test_a_job_linked_both_ways_is_counted_once(client):
    h, _home, uid = await _accountant(client, "p3@x.com")
    cid, corg = await _add_client(client, h, "Kaya Gıda")
    async with client._maker() as db:
        await _job(db, corg, uid, client_id=cid)  # in the client's org *and* labelled with it
        await db.commit()
        s = (await status_for_clients(db, [cid]))[cid]
    assert s.job_count == 1


@pytest.mark.asyncio
async def test_the_accountants_own_work_is_not_a_clients(client):
    h, home, uid = await _accountant(client, "p4@x.com")
    cid, _corg = await _add_client(client, h, "Kaya Gıda")
    async with client._maker() as db:
        await _job(db, home, uid)  # the accountant's own books, linked to nobody
        await db.commit()
        s = (await status_for_clients(db, [cid]))[cid]
    assert s.job_count == 0 and s.stage == "veri_yok"


@pytest.mark.asyncio
async def test_two_clients_do_not_share_work(client):
    h, _home, uid = await _accountant(client, "p5@x.com")
    a, aorg = await _add_client(client, h, "A Ltd")
    b, _borg = await _add_client(client, h, "B Ltd")
    async with client._maker() as db:
        await _job(db, aorg, uid)
        await db.commit()
        st = await status_for_clients(db, [a, b])
    assert st[a].job_count == 1 and st[b].job_count == 0


@pytest.mark.asyncio
async def test_a_legacy_client_without_an_org_still_works(client):
    h, home, uid = await _accountant(client, "p6@x.com")
    cid, _corg = await _add_client(client, h, "Eski Müşteri")
    async with client._maker() as db:
        from app.models.smmm_portal import SMMMMusteriKayit

        (await db.get(SMMMMusteriKayit, cid)).client_org_id = None  # a client from before M1
        await _job(db, home, uid, client_id=cid)  # filed under the accountant's org by the old form
        await db.commit()
        s = (await status_for_clients(db, [cid]))[cid]
    assert s.job_count == 1


@pytest.mark.asyncio
async def test_the_dashboard_counts_a_client_org_client(client):
    h, _home, uid = await _accountant(client, "p7@x.com")
    _cid, corg = await _add_client(client, h, "Kaya Gıda")
    async with client._maker() as db:
        job = await _job(db, corg, uid)
        await _pending(db, job, corg, 2)
        await db.commit()
    d = (await client.get(f"{P}/smmm/dashboard", headers=h)).json()
    s = d["summary"]
    assert s["analyzed_clients"] == 1 and s["pending_entries"] == 2 and s["needs_attention"] == 1
