"""SMMM M1: moving a client's old work into the client's own organisation.

The rule held here: the same money is never counted in two companies, a move
never loses a person's decision (it refuses instead), a dry run writes nothing,
and running it twice changes nothing the second time.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.canonical_transaction import CanonicalTransaction
from app.models.open_item import OpenItem
from app.models.open_item_match import OpenItemMatch
from app.models.organization import Organization, OrgMembership
from app.models.smmm_onay import OnayDurumu, SMMMOnayKaydi
from app.models.smmm_portal import SMMMMuhasebeci, SMMMMusteriKayit
from app.models.transaction import Transaction
from app.services.ledger import append_job
from app.services.smmm_adopt import DECIDED_MATCH, EXCLUDED_ROW, adopt_client_jobs
from tests.api_helpers import kullanici


async def _seed(client, *, with_org: bool = False):
    """An accountant at home with one client and two old jobs for it."""
    _h, home, uid = await kullanici(client, "acc@x.com", role="owner")
    async with client._maker() as db:
        m = SMMMMuhasebeci(user_id=uid, firma_adi="Müşavirlik")
        db.add(m)
        await db.flush()
        c = SMMMMusteriKayit(muhasebeci_id=m.id, firma_adi="Kaya Gıda")
        db.add(c)
        await db.flush()
        job_ids = []
        for n, (amount, desc) in enumerate([(100_00, "kira ocak"), (250_00, "maaş ocak")]):
            job = AnalysisJob(
                filename=f"{n}.csv", file_path=f"/{n}.csv", file_type="csv",
                org_id=home, user_id=uid, status=JobStatus.COMPLETED, smmm_client_id=c.id,
            )
            db.add(job)
            await db.flush()
            db.add(Transaction(
                job_id=job.id, amount_kurus=amount, currency="TRY", type="expense",
                category="rent", description=desc,
                transaction_date=datetime(2026, 1, 5 + n, tzinfo=UTC),
            ))
            await db.flush()
            await append_job(db, job.id)
            job_ids.append(job.id)
        db.add(SMMMOnayKaydi(
            job_id=job_ids[0], org_id=home, kayit_id="k1", orijinal_kayit={},
            durum=OnayDurumu.BEKLIYOR,
        ))
        await db.commit()
        return {"home": home, "uid": uid, "client": c.id, "jobs": job_ids}


async def _ledger_orgs(db, job_id):
    return {
        str(o)
        for o in (
            await db.execute(
                select(CanonicalTransaction.org_id).where(CanonicalTransaction.source_job_id == job_id)
            )
        ).scalars()
    }


@pytest.mark.asyncio
async def test_dry_run_writes_nothing(client):
    s = await _seed(client)
    async with client._maker() as db:
        r = await adopt_client_jobs(db, client_id=s["client"], dry_run=True)
        assert sorted(r.moved) == sorted(s["jobs"]) and r.created_org and r.dry_run
    async with client._maker() as db:
        assert (await db.get(SMMMMusteriKayit, s["client"])).client_org_id is None
        for j in s["jobs"]:
            assert (await db.get(AnalysisJob, j)).org_id == s["home"]
            assert await _ledger_orgs(db, j) == {s["home"]}
        assert (await db.execute(select(func.count()).select_from(Organization))).scalar_one() == 1


@pytest.mark.asyncio
async def test_apply_moves_jobs_and_ledger_and_never_counts_money_twice(client):
    s = await _seed(client)
    async with client._maker() as db:
        r = await adopt_client_jobs(db, client_id=s["client"], dry_run=False)
        assert not r.refused and r.client_org_id
        new_org = r.client_org_id

    async with client._maker() as db:
        org = await db.get(Organization, new_org)
        assert org.country_code == "TR" and org.name == "Kaya Gıda"
        roles = {
            m.org_id: m.role
            for m in (
                await db.execute(select(OrgMembership).where(OrgMembership.user_id == s["uid"]))
            ).scalars()
        }
        assert roles[new_org] == "smmm" and roles[s["home"]] == "owner"
        assert (await db.get(SMMMMusteriKayit, s["client"])).client_org_id == new_org

        for j in s["jobs"]:
            assert (await db.get(AnalysisJob, j)).org_id == new_org
            # The money is in the client's ledger and nowhere else.
            assert await _ledger_orgs(db, j) == {new_org}
        onay = (await db.execute(select(SMMMOnayKaydi))).scalar_one()
        assert onay.org_id == new_org
        home_rows = (
            await db.execute(
                select(func.count()).select_from(CanonicalTransaction)
                .where(CanonicalTransaction.org_id == s["home"])
            )
        ).scalar_one()
        assert home_rows == 0


@pytest.mark.asyncio
async def test_running_it_twice_changes_nothing_the_second_time(client):
    s = await _seed(client)
    async with client._maker() as db:
        first = await adopt_client_jobs(db, client_id=s["client"], dry_run=False)
    async with client._maker() as db:
        before = (await db.execute(select(func.count()).select_from(CanonicalTransaction))).scalar_one()
        second = await adopt_client_jobs(db, client_id=s["client"], dry_run=False)
        after = (await db.execute(select(func.count()).select_from(CanonicalTransaction))).scalar_one()
        orgs = (await db.execute(select(func.count()).select_from(Organization))).scalar_one()
    assert second.moved == [] and not second.created_org
    assert second.client_org_id == first.client_org_id
    assert before == after and orgs == 2


@pytest.mark.asyncio
async def test_a_job_with_an_excluded_row_is_refused_not_moved(client):
    s = await _seed(client)
    async with client._maker() as db:
        row = (
            await db.execute(
                select(CanonicalTransaction).where(CanonicalTransaction.source_job_id == s["jobs"][0])
            )
        ).scalars().first()
        row.ledger_status = "excluded"  # a person took this row out of the books
        await db.commit()
    async with client._maker() as db:
        r = await adopt_client_jobs(db, client_id=s["client"], dry_run=False)
    assert r.refused == {s["jobs"][0]: EXCLUDED_ROW}
    assert r.moved == [s["jobs"][1]]
    async with client._maker() as db:
        assert (await db.get(AnalysisJob, s["jobs"][0])).org_id == s["home"]
        assert await _ledger_orgs(db, s["jobs"][0]) == {s["home"]}  # untouched
        assert (await db.get(AnalysisJob, s["jobs"][1])).org_id == r.client_org_id


@pytest.mark.asyncio
async def test_a_job_in_an_org_the_accountant_is_not_in_is_refused(client):
    s = await _seed(client)
    async with client._maker() as db:
        stranger = Organization(name="Başkası", slug="baskasi")
        db.add(stranger)
        await db.flush()
        job = await db.get(AnalysisJob, s["jobs"][0])
        job.org_id = stranger.id
        await db.commit()
        stranger_id = stranger.id
    async with client._maker() as db:
        r = await adopt_client_jobs(db, client_id=s["client"], dry_run=False)
    assert s["jobs"][0] in r.refused
    async with client._maker() as db:
        assert (await db.get(AnalysisJob, s["jobs"][0])).org_id == stranger_id


@pytest.mark.asyncio
async def test_unrelated_jobs_stay_where_they_are(client):
    s = await _seed(client)
    async with client._maker() as db:
        other = AnalysisJob(
            filename="own.csv", file_path="/own.csv", file_type="csv",
            org_id=s["home"], user_id=s["uid"], status=JobStatus.COMPLETED,
        )
        db.add(other)
        await db.commit()
        other_id = other.id
    async with client._maker() as db:
        await adopt_client_jobs(db, client_id=s["client"], dry_run=False)
    async with client._maker() as db:
        assert (await db.get(AnalysisJob, other_id)).org_id == s["home"]


async def _item_with_match(db, s, *, decided_by):
    from datetime import date

    row = (
        await db.execute(
            select(CanonicalTransaction).where(CanonicalTransaction.source_job_id == s["jobs"][0])
        )
    ).scalars().first()
    item = OpenItem(
        org_id=s["home"], direction="payable", document_id="doc-1", source_job_id=s["jobs"][0],
        amount_cents=100_00, issue_date=date(2026, 1, 1),
    )
    db.add(item)
    await db.flush()
    db.add(OpenItemMatch(
        org_id=s["home"], open_item_id=item.id, ledger_row_id=row.id, amount_cents=100_00,
        method="manual", status="confirmed", matched_on=date(2026, 1, 5), decided_by=decided_by,
    ))
    await db.commit()


@pytest.mark.asyncio
async def test_a_match_a_person_decided_blocks_the_move(client):
    s = await _seed(client)
    async with client._maker() as db:
        await _item_with_match(db, s, decided_by=s["uid"])
    async with client._maker() as db:
        r = await adopt_client_jobs(db, client_id=s["client"], dry_run=False)
    assert r.refused == {s["jobs"][0]: DECIDED_MATCH}
    async with client._maker() as db:
        assert (await db.get(AnalysisJob, s["jobs"][0])).org_id == s["home"]
        assert (await db.execute(select(func.count()).select_from(OpenItemMatch))).scalar_one() == 1


@pytest.mark.asyncio
async def test_a_match_the_reconciler_made_does_not_block_and_its_old_rows_go(client):
    s = await _seed(client)
    async with client._maker() as db:
        await _item_with_match(db, s, decided_by=None)
    async with client._maker() as db:
        r = await adopt_client_jobs(db, client_id=s["client"], dry_run=False)
    assert not r.refused
    async with client._maker() as db:
        # No open item or match is left behind in the old company.
        left = (
            await db.execute(select(func.count()).select_from(OpenItem).where(OpenItem.org_id == s["home"]))
        ).scalar_one()
        assert left == 0
        assert (await db.execute(select(func.count()).select_from(OpenItemMatch))).scalar_one() == 0
