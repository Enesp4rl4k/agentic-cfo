"""Plan v10 G3: a category correction reaches the ledger row with the same source_record_id."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.audit_log import AuditLog
from app.models.canonical_transaction import CanonicalTransaction
from app.models.organization import Organization
from app.models.transaction import Transaction
from app.services.donem_kilidi import kilitle
from app.services.ledger import Period, append_job, company_rows, ledger_summary, month_of
from tests.api_helpers import kullanici

# Every period there is: a closed-month correction pair is booked after the last money month,
# which the default period (anchored on money) does not reach.
EVERYTHING = Period("2000-01", "2099-12")


async def _org(client, email):
    h, org, uid = await kullanici(client, email, role="owner")
    async with client._maker() as db:
        (await db.get(Organization, org)).regional_packs = ["tr"]
        await db.commit()
    return h, org, uid


async def _job(db, org, uid, rows):
    """rows: (date tuple, category, direction, kurus). Returns (job_id, [tx ids])."""
    job = AnalysisJob(filename="a.csv", file_path="/a.csv", file_type="csv",
                      org_id=org, user_id=uid, status=JobStatus.COMPLETED)
    db.add(job)
    await db.flush()
    ids = []
    for i, (day, cat, typ, kurus) in enumerate(rows):
        t = Transaction(job_id=job.id, amount_kurus=kurus, currency="TRY", type=typ,
                        category=cat, description=f"islem {i}",
                        transaction_date=datetime(*day, tzinfo=UTC))
        db.add(t)
        await db.flush()
        ids.append(t.id)
    await db.commit()
    return job.id, ids


async def _ledger(db, org):
    return (await db.execute(select(CanonicalTransaction).where(
        CanonicalTransaction.org_id == org).order_by(CanonicalTransaction.source_record_id))).scalars().all()


async def _audits(db):
    return (await db.execute(
        select(AuditLog).where(AuditLog.action == "ledger.category_correction"))).scalars().all()


def _by_cat(rows):
    out: dict[str, int] = {}
    for r in rows:
        out[r.category] = out.get(r.category, 0) + r.amount_cents
    return out


def _patch(client, h, tx_id, cat):
    return client.patch(f"/api/v1/transactions/{tx_id}/category", json={"category": cat}, headers=h)


@pytest.mark.asyncio
async def test_correction_updates_open_month_row_and_totals(client):
    h, org, uid = await _org(client, "g3a@x.com")
    async with client._maker() as db:
        job, (t1, _t2) = await _job(db, org, uid, [
            ((2026, 3, 4), "other_expense", "expense", 10_000),
            ((2026, 3, 5), "revenue", "income", 50_000)])
        await append_job(db, job)
        before = await ledger_summary(db, org)
    r = await _patch(client, h, t1, "rent")
    assert r.status_code == 200, r.text
    assert r.json()["data"]["ledger"] == "updated"
    async with client._maker() as db:
        view = await company_rows(db, org, EVERYTHING)
        after = await ledger_summary(db, org)
        audit = await _audits(db)
    assert _by_cat(view.profit) == {"rent": 10_000, "revenue": 50_000}
    assert after["expense_cents"] == before["expense_cents"]
    assert after["revenue_cents"] == before["revenue_cents"]
    assert len(audit) == 1 and audit[0].user_id == uid
    assert audit[0].request_body["old"] == "other_expense" and audit[0].request_body["new"] == "rent"


@pytest.mark.asyncio
async def test_double_submission_is_a_noop(client):
    h, org, uid = await _org(client, "g3b@x.com")
    async with client._maker() as db:
        job, (t1,) = await _job(db, org, uid, [((2026, 3, 4), "other_expense", "expense", 10_000)])
        await append_job(db, job)
    assert (await _patch(client, h, t1, "rent")).status_code == 200
    again = await _patch(client, h, t1, "rent")
    assert again.json()["data"]["ledger"] == "unchanged"
    async with client._maker() as db:
        rows = await _ledger(db, org)
        audit = await _audits(db)
    assert [(r.category, r.amount_cents) for r in rows] == [("rent", 10_000)]
    assert len(audit) == 1


@pytest.mark.asyncio
async def test_closed_month_keeps_original_and_books_correction_in_open_month(client):
    h, org, uid = await _org(client, "g3c@x.com")
    async with client._maker() as db:
        job, (t1,) = await _job(db, org, uid, [((2026, 1, 15), "other_expense", "expense", 10_000)])
        await append_job(db, job)
        await kilitle(db, org, "2026-01", uid)
        await db.commit()
        before = await ledger_summary(db, org)
    r = await _patch(client, h, t1, "rent")
    assert r.json()["data"]["ledger"] == "booked_in_open_month"
    async with client._maker() as db:
        rows = await _ledger(db, org)
        after = await ledger_summary(db, org)
    original = next(x for x in rows if x.source_type == "fingerprint")
    corr = [x for x in rows if x.source_type == "correction"]
    assert original.category == "other_expense" and month_of(original.transaction_date) == "2026-01"
    assert sorted((x.category, x.amount_cents) for x in corr) == [
        ("other_expense", -10_000), ("rent", 10_000)]
    assert all(month_of(x.transaction_date) == "2026-02" and x.asil_donem == "2026-01" for x in corr)
    assert all(x.source_record_id.startswith(original.source_record_id) for x in corr)
    assert after["expense_cents"] == before["expense_cents"]
    jan = [x for x in rows if month_of(x.transaction_date) == "2026-01"]
    assert _by_cat(jan) == {"other_expense": 10_000}  # the closed month's figures stay
    # same category again adds nothing; a further change chains off the effective category
    assert (await _patch(client, h, t1, "rent")).json()["data"]["ledger"] == "unchanged"
    assert (await _patch(client, h, t1, "technology")).json()["data"]["ledger"] == "booked_in_open_month"
    async with client._maker() as db:
        rows = await _ledger(db, org)
        view = await company_rows(db, org, EVERYTHING)
    assert len(rows) == 5
    assert _by_cat(view.profit) == {"other_expense": 0, "rent": 0, "technology": 10_000}


@pytest.mark.asyncio
async def test_rereading_the_job_does_not_undo_a_closed_month_correction(client):
    h, org, uid = await _org(client, "g3d@x.com")
    async with client._maker() as db:
        job, (t1,) = await _job(db, org, uid, [((2026, 1, 15), "other_expense", "expense", 10_000)])
        await append_job(db, job)
        await kilitle(db, org, "2026-01", uid)
        await db.commit()
    await _patch(client, h, t1, "rent")
    async with client._maker() as db:
        await append_job(db, job)
        view = await company_rows(db, org, EVERYTHING)
    assert _by_cat(view.profit) == {"other_expense": 0, "rent": 10_000}


@pytest.mark.asyncio
async def test_other_orgs_record_is_rejected(client):
    _ha, orga, ua = await _org(client, "g3e@x.com")
    hb, _orgb, _ub = await _org(client, "g3f@x.com")
    async with client._maker() as db:
        job, (t1,) = await _job(db, orga, ua, [((2026, 3, 4), "other_expense", "expense", 10_000)])
        await append_job(db, job)
    r = await _patch(client, hb, t1, "rent")
    assert r.status_code == 404
    async with client._maker() as db:
        rows = await _ledger(db, orga)
        tx = await db.get(Transaction, t1)
    assert rows[0].category == "other_expense" and tx.category == "other_expense"
