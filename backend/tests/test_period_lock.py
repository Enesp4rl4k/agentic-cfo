"""SMMM M4: a period the accountant closed does not change; late changes land in the next open one.

Owner's decision (2026-11-21): a change that belongs to a closed month is booked as a
correction in the first open month, marked with the closed period it belongs to. The
closed month's figures (what was declared, what the e-Defter says) stay as they were.

First slice, held here:
* the lock itself: one row per organisation and month; only a role that decides
  entries may close a month; a future month cannot be closed; nobody sees another
  organisation's locks;
* the ledger honours it: a new row dated in a closed month is written into the first
  open month (its own date and its closed period kept beside it), and an existing row
  of a closed month is not rewritten when the same job is read again.
Accountant decisions and category corrections on a closed month are the next slice.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.canonical_transaction import CanonicalTransaction
from app.models.organization import Organization
from app.models.transaction import Transaction
from app.services.donem_kilidi import ilk_acik_donem, kilitle, kilitli_donemler
from app.services.ledger import append_job, month_of
from tests.api_helpers import kullanici

P = "/api/v1/smmm/donem-kilitleri"


def test_the_first_open_month_skips_every_closed_one():
    assert ilk_acik_donem("2026-01", {"2026-01", "2026-02"}) == "2026-03"
    assert ilk_acik_donem("2026-12", {"2026-12"}) == "2027-01"
    assert ilk_acik_donem("2026-05", set()) == "2026-05"


async def _org(client, email, role="owner"):
    h, org, uid = await kullanici(client, email, role=role)
    async with client._maker() as db:
        (await db.get(Organization, org)).regional_packs = ["tr"]
        await db.commit()
    return h, org, uid


async def _job_with(db, org, uid, rows):
    job = AnalysisJob(filename="a.csv", file_path="/a.csv", file_type="csv",
                      org_id=org, user_id=uid, status=JobStatus.COMPLETED)
    db.add(job)
    await db.flush()
    for i, (day, cat) in enumerate(rows):
        db.add(Transaction(job_id=job.id, amount_kurus=10_000 + i, currency="TRY", type="expense",
                           category=cat, description=f"kira {i}",
                           transaction_date=datetime(*day, tzinfo=UTC)))
    await db.flush()
    return job.id


async def _rows(db, org):
    return (await db.execute(select(CanonicalTransaction).where(CanonicalTransaction.org_id == org))).scalars().all()


@pytest.mark.asyncio
async def test_a_new_row_for_a_closed_month_lands_in_the_first_open_month(client):
    _h, org, uid = await _org(client, "d1@x.com")
    async with client._maker() as db:
        await kilitle(db, org, "2026-01", uid)
        job = await _job_with(db, org, uid, [((2026, 1, 15), "rent"), ((2026, 3, 4), "rent")])
        await db.commit()
        await append_job(db, job)
        rows = sorted(await _rows(db, org), key=lambda r: r.amount_cents)
    late, normal = rows
    assert month_of(late.transaction_date) == "2026-02"  # counted in the first open month
    assert late.asil_donem == "2026-01"
    assert late.asil_tarih.date().isoformat() == "2026-01-15"  # its own date, kept
    assert normal.asil_donem is None and month_of(normal.transaction_date) == "2026-03"


@pytest.mark.asyncio
async def test_a_row_of_a_closed_month_is_not_rewritten_when_read_again(client):
    _h, org, uid = await _org(client, "d2@x.com")
    async with client._maker() as db:
        job = await _job_with(db, org, uid, [((2026, 1, 15), "rent")])
        await db.commit()
        await append_job(db, job)
        await kilitle(db, org, "2026-01", uid)
        tx = (await db.execute(select(Transaction).where(Transaction.job_id == job))).scalar_one()
        tx.category = "utilities"  # a later reading of the same money
        await db.commit()
        await append_job(db, job)
        (row,) = await _rows(db, org)
    assert row.category == "rent" and month_of(row.transaction_date) == "2026-01"


@pytest.mark.asyncio
async def test_an_open_month_is_unaffected(client):
    _h, org, uid = await _org(client, "d3@x.com")
    async with client._maker() as db:
        await kilitle(db, org, "2026-01", uid)
        job = await _job_with(db, org, uid, [((2026, 2, 10), "rent")])
        await db.commit()
        await append_job(db, job)
        (row,) = await _rows(db, org)
    assert row.asil_donem is None and row.asil_tarih is None
    assert month_of(row.transaction_date) == "2026-02"


@pytest.mark.asyncio
async def test_locks_belong_to_one_organisation(client):
    _ha, a, ua = await _org(client, "d4@x.com")
    _hb, b, _ub = await _org(client, "d5@x.com")
    async with client._maker() as db:
        await kilitle(db, a, "2026-01", ua)
        await db.commit()
        assert await kilitli_donemler(db, a) == {"2026-01"}
        assert await kilitli_donemler(db, b) == set()


# ── through the routes ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_closing_a_month_and_listing_it(client):
    h, _org_id, _uid = await _org(client, "d6@x.com")
    r = await client.post(P, json={"donem": "2025-12"}, headers=h)
    assert r.status_code == 200, r.text
    listed = (await client.get(P, headers=h)).json()["data"]["donemler"]
    assert [x["donem"] for x in listed] == ["2025-12"] and listed[0]["kilitleyen_user_id"]


@pytest.mark.asyncio
async def test_closing_twice_is_a_conflict(client):
    h, *_ = await _org(client, "d7@x.com")
    assert (await client.post(P, json={"donem": "2025-11"}, headers=h)).status_code == 200
    assert (await client.post(P, json={"donem": "2025-11"}, headers=h)).status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize("donem", ["2099-01", "2026-13", "26-01", "ocak"])
async def test_a_future_or_malformed_month_cannot_be_closed(client, donem):
    h, *_ = await _org(client, f"d8-{donem}@x.com")
    assert (await client.post(P, json={"donem": donem}, headers=h)).status_code == 422


@pytest.mark.asyncio
async def test_a_role_that_does_not_decide_cannot_close_a_month(client):
    h, *_ = await _org(client, "d9@x.com", role="viewer")
    assert (await client.post(P, json={"donem": "2025-10"}, headers=h)).status_code == 403
    assert (await client.get(P, headers=h)).status_code == 200  # but may read


@pytest.mark.asyncio
async def test_another_organisations_locks_are_not_listed(client):
    ha, *_ = await _org(client, "d10@x.com")
    hb, *_ = await _org(client, "d11@x.com")
    await client.post(P, json={"donem": "2025-09"}, headers=ha)
    assert (await client.get(P, headers=hb)).json()["data"]["donemler"] == []
