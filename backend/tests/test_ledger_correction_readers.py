"""G3 hardening: a closed-month category correction is a reclassification, never money.

Every reader of `canonical_transactions` either ignores correction rows (`money_rows()`:
counts, sums, detectors, matchers) or reads the pair through the row it corrects (the
by-category profit view). These tests pin that for each reader, plus the sequences and
edge cases around closing months, reruns and races.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, select

from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.canonical_transaction import CanonicalTransaction
from app.models.open_item_match import OpenItemMatch
from app.models.transaction import Transaction
from app.services.donem_kilidi import DonemHatasi, kilitle, sonraki
from app.services.ledger import append_job, company_rows, ledger_summary, month_of
from app.services.ledger_correction import apply_overrides
from app.services.recurring_obligations import detect_recurring_obligations
from app.services.semantic.rebuild import _load_canonical
from app.services.tax_calendar import get_historical_tax_averages
from tests.test_ledger_category_correction import _by_cat, _job, _ledger, _org, _patch


def _correction_rows(rows):
    return [r for r in rows if r.corrects_id is not None]


async def _closed_jan(client, email, rows):
    """An appended job whose January is closed. Returns (headers, org, user, job, tx ids)."""
    h, org, uid = await _org(client, email)
    async with client._maker() as db:
        job, ids = await _job(db, org, uid, rows)
        await append_job(db, job)
        await kilitle(db, org, "2026-01", uid)
        await db.commit()
    return h, org, uid, job, ids


async def _per_month(client, org):
    async with client._maker() as db:
        view = await company_rows(db, org)
    out: dict[tuple[str, str | None], int] = {}
    for r in view.profit:
        key = (month_of(r.transaction_date), r.category)
        out[key] = out.get(key, 0) + r.amount_cents
    return out


# -- sequences on a closed month ------------------------------------------------

@pytest.mark.asyncio
async def test_a_to_b_to_c_nets_to_the_last_category_and_keeps_january(client):
    h, org, _uid, _job_id, (t1,) = await _closed_jan(
        client, "r1@x.com", [((2026, 1, 15), "other_expense", "expense", 10_000)])
    await _patch(client, h, t1, "rent")
    await _patch(client, h, t1, "technology")
    per = await _per_month(client, org)
    assert per[("2026-01", "other_expense")] == 10_000          # the closed month, as it was
    assert {k: v for k, v in per.items() if k[0] == "2026-02"} == {
        ("2026-02", "other_expense"): -10_000, ("2026-02", "rent"): 0, ("2026-02", "technology"): 10_000}
    async with client._maker() as db:
        s = await ledger_summary(db, org)
    assert s["expense_cents"] == 10_000


@pytest.mark.asyncio
async def test_a_to_b_to_a_returns_to_the_original_category_overall(client):
    h, org, _u, _j, (t1,) = await _closed_jan(
        client, "r2@x.com", [((2026, 1, 15), "other_expense", "expense", 10_000)])
    await _patch(client, h, t1, "rent")
    back = await _patch(client, h, t1, "other_expense")
    assert back.json()["data"]["ledger"] == "booked_in_open_month"
    per = await _per_month(client, org)
    assert sum(v for (m, c), v in per.items() if c == "other_expense") == 10_000
    assert sum(v for (m, c), v in per.items() if c == "rent") == 0
    assert per[("2026-01", "other_expense")] == 10_000


# -- every reader ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_semantic_totals_do_not_move_on_a_correction(client):
    h, org, _u, _j, (t1, _t2) = await _closed_jan(
        client, "r3@x.com", [((2026, 1, 15), "other_expense", "expense", 100_000),
                             ((2026, 3, 2), "revenue", "income", 500_000)])
    async with client._maker() as db:
        before, _ = await _load_canonical(org, db)
    await _patch(client, h, t1, "rent")
    async with client._maker() as db:
        after, _ = await _load_canonical(org, db)
    assert (after.count, after.inflow_cents, after.outflow_cents) == (
        before.count, before.inflow_cents, before.outflow_cents) == (2, 500_000, 100_000)


async def _sgk_job(db, org, uid, rows):
    job = AnalysisJob(filename="a.csv", file_path="/a.csv", file_type="csv", org_id=org, user_id=uid,
                      status=JobStatus.COMPLETED)
    db.add(job)
    await db.flush()
    ids = []
    for day, kurus, text in rows:
        t = Transaction(job_id=job.id, amount_kurus=kurus, currency="TRY", type="expense",
                        category="other_expense", description=text,
                        transaction_date=datetime(*day, tzinfo=UTC))
        db.add(t)
        await db.flush()
        ids.append(t.id)
    await db.commit()
    return job.id, ids


@pytest.mark.asyncio
async def test_tax_medians_ignore_correction_rows(client):
    h, org, uid = await _org(client, "r4@x.com")
    async with client._maker() as db:
        job, (t1, _t2) = await _sgk_job(db, org, uid, [
            ((2026, 1, 15), 10_000, "SGK prim odemesi"), ((2026, 2, 15), 30_000, "SGK prim odemesi")])
        await append_job(db, job)
        await kilitle(db, org, "2026-01", uid)
        await db.commit()
        before = await get_historical_tax_averages(db, org)
    assert before == {"sgk": 30_000}
    assert (await _patch(client, h, t1, "tax_payment")).json()["data"]["ledger"] == "booked_in_open_month"
    async with client._maker() as db:
        assert await get_historical_tax_averages(db, org) == before


@pytest.mark.asyncio
async def test_recurring_detection_sees_no_extra_occurrence(client):
    h, org, uid = await _org(client, "r5@x.com")
    rows = [((2026, m, 5), 50_000, "Levent ofis kira") for m in (1, 2, 3)]
    async with client._maker() as db:
        job, ids = await _sgk_job(db, org, uid, rows)
        await append_job(db, job)
        await kilitle(db, org, "2026-01", uid)
        await db.commit()
        before = await detect_recurring_obligations(db, org)
    assert len(before) == 1 and len(before[0].source_row_ids) == 3
    await _patch(client, h, ids[0], "rent")
    async with client._maker() as db:
        after = await detect_recurring_obligations(db, org)
        originals = {r.id for r in await _ledger(db, org) if r.corrects_id is None}
    assert len(after) == 1 and after[0].amount_cents == before[0].amount_cents
    assert len(after[0].source_row_ids) == 3 and set(after[0].source_row_ids) <= originals


@pytest.mark.asyncio
async def test_a_settling_cash_row_keeps_its_treatment_for_the_pair(client):
    h, org, _uid, _j, (t1, _t2) = await _closed_jan(
        client, "r6@x.com", [((2026, 1, 15), "other_expense", "expense", 10_000),
                             ((2026, 3, 2), "revenue", "income", 70_000)])
    async with client._maker() as db:
        original = next(r for r in await _ledger(db, org) if r.amount_cents == 10_000)
        db.add(OpenItemMatch(org_id=org, open_item_id="oi-1", ledger_row_id=original.id,
                             amount_cents=10_000, method="by_amount", status="confirmed",
                             matched_on=datetime(2026, 1, 15, tzinfo=UTC).date()))
        await db.commit()
        before = _by_cat((await company_rows(db, org)).profit)
    assert before == {"revenue": 70_000}                         # the settling row is cash, not profit
    await _patch(client, h, t1, "rent")
    async with client._maker() as db:
        after = _by_cat((await company_rows(db, org)).profit)
        cash = _by_cat((await company_rows(db, org)).cash)
    assert after == {"revenue": 70_000}                          # the pair follows the original out
    assert cash == {"other_expense": 10_000, "revenue": 70_000}  # a reclassification moves no cash


@pytest.mark.asyncio
async def test_income_and_expense_signs_and_the_account_are_kept(client):
    h, org, _uid, _j, (t_exp, t_inc) = await _closed_jan(
        client, "r7@x.com", [((2026, 1, 15), "other_expense", "expense", 10_000),
                             ((2026, 1, 16), "revenue", "income", 40_000)])
    async with client._maker() as db:
        before = await ledger_summary(db, org)
    await _patch(client, h, t_exp, "rent")
    await _patch(client, h, t_inc, "other_income")
    async with client._maker() as db:
        after = await ledger_summary(db, org)
        rows = await _ledger(db, org)
    assert (after["expense_cents"], after["revenue_cents"]) == (before["expense_cents"], before["revenue_cents"])
    by = sorted((r.direction, r.category, r.amount_cents) for r in _correction_rows(rows))
    assert by == [("expense", "other_expense", -10_000), ("expense", "rent", 10_000),
                  ("income", "other_income", 40_000), ("income", "revenue", -40_000)]
    originals = {r.id: r for r in rows if r.corrects_id is None}
    assert all(r.account_code == originals[r.corrects_id].account_code for r in _correction_rows(rows))


# -- order of events and edges --------------------------------------------------------

@pytest.mark.asyncio
async def test_month_closed_after_an_open_month_correction(client):
    h, org, uid = await _org(client, "r8@x.com")
    async with client._maker() as db:
        job, (t1,) = await _job(db, org, uid, [((2026, 1, 15), "other_expense", "expense", 10_000)])
        await append_job(db, job)
    assert (await _patch(client, h, t1, "rent")).json()["data"]["ledger"] == "updated"
    async with client._maker() as db:
        await kilitle(db, org, "2026-01", uid)
        await db.commit()
        await append_job(db, job)                                 # a re-read does not touch it
        (row,) = await _ledger(db, org)
    assert row.category == "rent" and month_of(row.transaction_date) == "2026-01"
    assert (await _patch(client, h, t1, "technology")).json()["data"]["ledger"] == "booked_in_open_month"
    async with client._maker() as db:
        rows = await _ledger(db, org)
    assert next(r for r in rows if r.corrects_id is None).category == "rent"   # closed: untouched
    assert len(_correction_rows(rows)) == 2


@pytest.mark.asyncio
async def test_with_the_recent_months_closed_the_pair_lands_next_month(client):
    """The first open month always exists: a future month cannot be closed, so at worst the next one."""
    now = datetime.now(UTC)
    this = now.strftime("%Y-%m")
    prev = f"{now.year - 1}-12" if now.month == 1 else f"{now.year}-{now.month - 1:02d}"
    h, org, uid = await _org(client, "r9@x.com")
    async with client._maker() as db:
        job, (t1,) = await _job(db, org, uid, [((int(prev[:4]), int(prev[5:]), 5), "other_expense", "expense", 10_000)])
        await append_job(db, job)
        await kilitle(db, org, prev, uid)
        await kilitle(db, org, this, uid)
        await db.commit()
    assert (await _patch(client, h, t1, "rent")).status_code == 200
    async with client._maker() as db:
        rows = await _ledger(db, org)
    assert {month_of(r.transaction_date) for r in _correction_rows(rows)} == {sonraki(this)}
    assert all(r.asil_donem == prev for r in _correction_rows(rows))


@pytest.mark.asyncio
async def test_a_correction_row_is_not_a_transaction_and_cannot_be_corrected(client):
    h, org, _u, _j, (t1,) = await _closed_jan(
        client, "r10@x.com", [((2026, 1, 15), "other_expense", "expense", 10_000)])
    await _patch(client, h, t1, "rent")
    async with client._maker() as db:
        corr = _correction_rows(await _ledger(db, org))[0]
    assert (await _patch(client, h, corr.id, "technology")).status_code == 404


@pytest.mark.asyncio
async def test_a_closed_possible_duplicate_is_held_not_booked(client):
    h, org, _uid, _j, (t1,) = await _closed_jan(
        client, "r11@x.com", [((2026, 1, 15), "other_expense", "expense", 10_000)])
    async with client._maker() as db:
        (row,) = await _ledger(db, org)
        row.ledger_status = "possible_duplicate"
        await db.commit()
    assert (await _patch(client, h, t1, "rent")).json()["data"]["ledger"] == "held"
    async with client._maker() as db:
        assert len(await _ledger(db, org)) == 1


# -- rerun, races ------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_rerun_keeps_a_single_row_correction_open_and_closed(client):
    h, org, uid = await _org(client, "r12@x.com")
    async with client._maker() as db:
        job, (t_open, t_closed) = await _job(db, org, uid, [
            ((2026, 3, 4), "other_expense", "expense", 10_000),
            ((2026, 1, 15), "other_expense", "expense", 20_000)])
        await append_job(db, job)
        await kilitle(db, org, "2026-01", uid)
        await db.commit()
    await _patch(client, h, t_open, "rent")
    await _patch(client, h, t_closed, "technology")
    # A rerun, as the worker does it: the old rows go, new rows come with the pipeline's categories.
    async with client._maker() as db:
        old = (await db.execute(select(Transaction).where(Transaction.job_id == job))).scalars().all()
        fresh = [(t.amount_kurus, t.transaction_date, t.description) for t in old]
        await db.execute(delete(Transaction).where(Transaction.job_id == job))
        for kurus, when, text in fresh:
            db.add(Transaction(job_id=job, amount_kurus=kurus, currency="TRY", type="expense",
                               category="other_expense", description=text, transaction_date=when))
        assert await apply_overrides(db, org, job) == 2
        await db.commit()
        await append_job(db, job)
        rows = await _ledger(db, org)
        view = await company_rows(db, org)
    originals = {r.amount_cents: r for r in rows if r.corrects_id is None}
    assert originals[10_000].category == "rent"                  # open month: stays corrected
    assert originals[20_000].category == "other_expense"         # closed month: untouched
    assert _by_cat(view.profit)["technology"] == 20_000 and len(_correction_rows(rows)) == 2


@pytest.mark.asyncio
async def test_a_colliding_correction_is_a_409_and_writes_nothing(client):
    h, org, _u, _j, (t1,) = await _closed_jan(
        client, "r13@x.com", [((2026, 1, 15), "other_expense", "expense", 10_000)])
    async with client._maker() as db:
        (row,) = await _ledger(db, org)
        db.add(CanonicalTransaction(  # what a concurrent correction would have written first
            org_id=org, source_type="correction", source_record_id=f"{row.source_record_id}~k1-iptal",
            transaction_date=row.transaction_date, amount_cents=1, direction="expense", basis="cash"))
        await db.commit()
    r = await _patch(client, h, t1, "rent")
    assert r.status_code == 409
    async with client._maker() as db:
        assert len(await _ledger(db, org)) == 2                   # the original and the stray; no pair


@pytest.mark.asyncio
async def test_a_racing_double_close_is_a_conflict_not_a_500(client, monkeypatch):
    _h, org, uid = await _org(client, "r14@x.com")
    async with client._maker() as db:
        await kilitle(db, org, "2026-01", uid)
        await db.commit()
        from app.services import donem_kilidi

        async def blind(*_a, **_k):
            return set()          # the second closer's check ran before the first committed

        monkeypatch.setattr(donem_kilidi, "kilitli_donemler", blind)
        with pytest.raises(DonemHatasi, match="zaten"):
            await kilitle(db, org, "2026-01", uid)
