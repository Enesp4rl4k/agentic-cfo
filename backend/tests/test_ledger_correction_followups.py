"""G3 follow-ups: a closed-month correction pair is a reclassification everywhere it is read.

1. the CFO pipeline's anomaly detectors never see the pair as payments;
2. a month holding only the pair is not a period;
3. chat evidence matches a corrected row by its effective category;
4. a person's overrides live and die with the ledger they correct;
5. an append takes the organisation lock before it reads the closed months.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.agents.anomaly_agent import (
    detect_duplicates,
    detect_unusual_amounts,
    run_anomaly_detection,
)
from app.agents.multi_period_agent import _aggregate_by_month, _compute_mom
from app.models.category_override import CategoryOverride
from app.services import ledger as ledger_mod
from app.services.company_view import ledger_view
from app.services.demo_template import purge_demo_workspace
from app.services.donem_kilidi import kilitle
from app.services.ledger import append_job
from app.services.ledger_correction import apply_overrides
from app.services.rag.ledger_evidence import retrieve_ledger_evidence
from tests.test_ledger_category_correction import EVERYTHING, _job, _ledger, _org, _patch
from tests.test_ledger_correction_readers import _closed_jan


def _tx(day, amount, cat, vendor="Levent Kira", corrects=None, typ="expense"):
    return {"id": f"{day}-{amount}-{cat}-{bool(corrects)}", "transaction_date": day, "amount_cents": amount,
            "category": cat, "vendor": vendor, "type": typ, "corrects_id": corrects}


# -- 1. anomalies -----------------------------------------------------------------

def test_correction_pair_is_not_a_duplicate_payment_or_an_outlier():
    original = _tx("2026-01-31", 10_000, "other_expense")   # the pair is booked a day later
    pair = [_tx("2026-02-01", -10_000, "other_expense", corrects="x"),
            _tx("2026-02-01", 10_000, "rent", corrects="x")]
    assert detect_duplicates([original, *pair]) == []
    # A real repeat is still found.
    assert len(detect_duplicates([original, _tx("2026-02-01", 10_000, "other_expense")])) == 1
    spread = [_tx(f"2026-01-{d:02d}", 10_000 + d, "other_expense", vendor=f"v{d}") for d in range(1, 11)]
    assert detect_unusual_amounts([*spread, *pair]) == detect_unusual_amounts(spread)


@pytest.mark.asyncio
async def test_pipeline_from_the_ledger_flags_nothing_for_a_corrected_closed_month(client):
    h, org, _u, _j, (t1,) = await _closed_jan(
        client, "f1@x.com", [((2026, 1, 15), "other_expense", "expense", 10_000)])
    await _patch(client, h, t1, "rent")
    async with client._maker() as db:
        view = await ledger_view(db, org, EVERYTHING)
    assert view is not None
    assert sum(1 for t in view.profit if t["corrects_id"]) == 2
    rows = [{**t, "vendor": "Levent"} for t in view.profit]
    assert detect_duplicates(rows) == []
    out = await run_anomaly_detection({"transactions": rows}, None)  # type: ignore[arg-type]
    kinds = {a["anomaly_type"] for a in out.patch["anomalies"]}
    assert not kinds & {"duplicate_payment", "unusual_amount", "expense_spike"}
    by_cat: dict[str, int] = {}
    for t in view.profit:
        by_cat[t["category"]] = by_cat.get(t["category"], 0) + t["amount_cents"]
    assert by_cat == {"other_expense": 0, "rent": 10_000}   # category totals stay right


# -- 2. phantom month -------------------------------------------------------------

def test_a_month_with_only_correction_rows_is_not_a_period():
    rows = [_tx("2026-01-15", 50_000, "revenue", typ="income"), _tx("2026-03-02", 60_000, "revenue", typ="income"),
            _tx("2026-02-01", -10_000, "other_expense", corrects="x"),
            _tx("2026-02-01", 10_000, "rent", corrects="x")]
    monthly = _aggregate_by_month(rows)
    assert sorted(monthly) == ["2026-01", "2026-03"]
    mom = _compute_mom(monthly)
    assert mom is not None and mom["previous_month"] == "2026-01" and mom["revenue_change_pct"] == 20.0


def test_a_correction_in_a_real_month_still_moves_its_category():
    rows = [_tx("2026-02-03", 5_000, "other_expense"),
            _tx("2026-02-01", -10_000, "other_expense", corrects="x"),
            _tx("2026-02-01", 10_000, "rent", corrects="x")]
    m = _aggregate_by_month(rows)["2026-02"]
    assert m["expenses"] == 5_000 and m["rent"] == 10_000


# -- 3. chat evidence -------------------------------------------------------------

@pytest.mark.asyncio
async def test_evidence_matches_the_corrected_category_of_a_closed_month_row(client):
    h, org, _u, _j, (t1,) = await _closed_jan(
        client, "f3@x.com", [((2026, 1, 15), "other_expense", "expense", 10_000)])
    await _patch(client, h, t1, "rent")
    async with client._maker() as db:
        new = await retrieve_ledger_evidence(db=db, org_id=org, query="rent", top_k=5)
        old = await retrieve_ledger_evidence(db=db, org_id=org, query="other expense", top_k=5)
        rows = await _ledger(db, org)
    assert len(new.citations) == 1 and "2026-01-15" in new.citations[0].preview   # the original, once
    assert old.citations == []
    assert sum(1 for r in rows if r.corrects_id is None) == 1


# -- 4. overrides -----------------------------------------------------------------

@pytest.mark.asyncio
async def test_demo_purge_removes_the_orgs_category_overrides(client):
    _h, org, uid = await _org(client, "f4@x.com")
    async with client._maker() as db:
        db.add(CategoryOverride(org_id=org, source_record_id="fp:abc#1", category="rent", user_id=uid))
        db.add(CategoryOverride(org_id="other-org", source_record_id="fp:abc#1", category="rent"))
        await db.commit()
        await purge_demo_workspace(db, org)
        left = (await db.execute(select(CategoryOverride.org_id))).scalars().all()
    assert left == ["other-org"]


@pytest.mark.asyncio
async def test_correcting_back_to_the_original_leaves_a_neutral_override(client):
    h, org, _uid, job, (t1,) = await _closed_jan(
        client, "f4b@x.com", [((2026, 1, 15), "other_expense", "expense", 10_000)])
    await _patch(client, h, t1, "rent")
    await _patch(client, h, t1, "other_expense")
    async with client._maker() as db:
        kept = (await db.execute(select(CategoryOverride).where(CategoryOverride.org_id == org))).scalars().all()
        assert [k.category for k in kept] == ["other_expense"]   # the person's last word = the pipeline's
        # A rerun that reads the same category changes nothing about the row.
        assert await apply_overrides(db, org, job) == 0


# -- 5. append vs month close -----------------------------------------------------

@pytest.mark.asyncio
async def test_append_locks_the_organisation_before_reading_closed_months(client, monkeypatch):
    _h, org, uid = await _org(client, "f5@x.com")
    calls: list[str] = []
    from app.services import donem_kilidi

    real_lock, real_closed = ledger_mod.lock_org, donem_kilidi.kilitli_donemler

    async def lock(db, org_id):
        calls.append("lock")
        await real_lock(db, org_id)

    async def closed(db, org_id):
        calls.append("closed")
        return await real_closed(db, org_id)

    monkeypatch.setattr(ledger_mod, "lock_org", lock)
    monkeypatch.setattr(donem_kilidi, "kilitli_donemler", closed)
    async with client._maker() as db:
        job, _ids = await _job(db, org, uid, [((2026, 1, 15), "other_expense", "expense", 10_000)])
        await append_job(db, job)
        await kilitle(db, org, "2026-01", uid)
    assert calls[:2] == ["lock", "closed"]
