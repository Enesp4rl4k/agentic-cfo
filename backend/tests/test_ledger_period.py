"""G8 / plan v10 S1.4: the ledger is read for a period, 12 months of data by default.

A row belongs to the month it is booked in, so a correction pair and a late item written
into the first open month count there, and adjacent periods add up to their union.
"""
from __future__ import annotations

import pytest

from app.services.company_view import ledger_view
from app.services.donem_kilidi import kilitle
from app.services.ledger import Period, add_months, append_job, company_rows, ledger_summary
from tests.test_ledger_category_correction import _job, _ledger, _org, _patch


def _thirteen():
    """One income of 1000 * n kurus in each month 2025-01 .. 2026-01 (n = 1..13)."""
    out = []
    for n in range(13):
        year, month = divmod(n, 12)
        out.append(((2025 + year, month + 1, 10), "revenue", "income", 1000 * (n + 1)))
    return out


async def _appended(client, email, rows):
    h, org, uid = await _org(client, email)
    async with client._maker() as db:
        job, ids = await _job(db, org, uid, rows)
        await append_job(db, job)
    return h, org, uid, job, ids


async def _summary(client, h, query=""):
    res = await client.get(f"/api/v1/ledger/summary{query}", headers=h)
    return res.status_code, res.json().get("data")


def test_add_months_crosses_years():
    assert add_months("2026-01", -11) == "2025-02"
    assert add_months("2025-12", 1) == "2026-01"
    assert add_months("2026-03", -14) == "2025-01"


@pytest.mark.asyncio
async def test_default_is_the_last_twelve_months_of_data_with_its_label(client):
    h, *_ = await _appended(client, "p1@x.com", _thirteen())
    status, data = await _summary(client, h)
    assert status == 200
    assert data["period"] == {
        "start": "2025-02", "end": "2026-01", "months": 12, "label": "2025-02 – 2026-01",
        "is_default": True, "available_start": "2025-01", "available_end": "2026-01",
        "available_months": 13,
    }
    assert data["rows"] == 12
    assert data["revenue_cents"] == sum(1000 * n for n in range(2, 14))     # January 2025 is out
    assert next(m["month"] for m in data["months"]) == "2025-02"


@pytest.mark.asyncio
async def test_less_than_a_year_of_data_is_all_of_it(client):
    h, *_ = await _appended(client, "p2@x.com", _thirteen()[:5])
    _, data = await _summary(client, h)
    assert (data["period"]["start"], data["period"]["end"], data["period"]["months"]) == ("2025-01", "2025-05", 5)


@pytest.mark.asyncio
async def test_an_explicit_period_is_used_as_asked(client):
    h, *_ = await _appended(client, "p3@x.com", _thirteen())
    _, data = await _summary(client, h, "?start=2025-03&end=2025-05")
    assert data["revenue_cents"] == 3000 + 4000 + 5000
    assert data["period"]["label"] == "2025-03 – 2025-05" and data["period"]["is_default"] is False
    # Only an end: twelve months ending there (no earlier than the data).
    _, data = await _summary(client, h, "?end=2025-06")
    assert (data["period"]["start"], data["period"]["end"]) == ("2025-01", "2025-06")
    assert data["revenue_cents"] == 1000 * (1 + 2 + 3 + 4 + 5 + 6)


@pytest.mark.asyncio
async def test_an_empty_period_is_zero_and_says_so(client):
    h, *_ = await _appended(client, "p4@x.com", _thirteen())
    _, data = await _summary(client, h, "?start=2020-01&end=2020-03")
    assert data["rows"] == 0 and data["revenue_cents"] == 0 and data["months"] == []
    assert data["period"]["months"] == 0 and data["period"]["label"] == "2020-01 – 2020-03"
    assert data["period"]["available_months"] == 13


@pytest.mark.asyncio
async def test_an_empty_ledger_has_no_period(client):
    h, _org_id, _u = await _org(client, "p5@x.com")
    _, data = await _summary(client, h)
    assert data["period"]["start"] is None and data["period"]["label"] is None and data["rows"] == 0


@pytest.mark.asyncio
async def test_invalid_periods_are_refused(client):
    h, _o, _u = await _org(client, "p6@x.com")
    for query in ("?start=2026-13", "?start=2026-3&end=2026-04", "?start=2026-05&end=2026-04", "?end=abc"):
        assert (await client.get(f"/api/v1/ledger/summary{query}", headers=h)).status_code == 400


@pytest.mark.asyncio
async def test_month_boundaries_are_inclusive_and_exact(client):
    rows = [((2025, 1, 31), "revenue", "income", 100), ((2025, 2, 1), "revenue", "income", 200),
            ((2025, 2, 28), "revenue", "income", 400), ((2025, 3, 1), "revenue", "income", 800)]
    h, *_ = await _appended(client, "p7@x.com", rows)
    assert (await _summary(client, h, "?start=2025-01&end=2025-01"))[1]["revenue_cents"] == 100
    assert (await _summary(client, h, "?start=2025-02&end=2025-02"))[1]["revenue_cents"] == 600
    assert (await _summary(client, h, "?start=2025-02&end=2025-03"))[1]["revenue_cents"] == 1400


@pytest.mark.asyncio
async def test_adjacent_periods_add_up_to_their_union(client):
    _h, org, *_ = await _appended(client, "p8@x.com", _thirteen())
    async with client._maker() as db:
        parts = [await ledger_summary(db, org, Period(a, b))
                 for a, b in (("2025-01", "2025-06"), ("2025-07", "2026-01"))]
        whole = await ledger_summary(db, org, Period("2025-01", "2026-01"))
    for key in ("rows", "revenue_cents", "expense_cents"):
        assert sum(p[key] for p in parts) == whole[key]
    assert sum(len(p["months"]) for p in parts) == len(whole["months"]) == 13
    assert whole["revenue_cents"] == sum(1000 * n for n in range(1, 14))


@pytest.mark.asyncio
async def test_a_correction_pair_belongs_to_the_month_it_is_booked_in(client):
    h, org, uid = await _org(client, "p9@x.com")
    async with client._maker() as db:
        job, (t1, _t2) = await _job(db, org, uid, [((2026, 1, 15), "other_expense", "expense", 10_000),
                                                    ((2026, 3, 5), "revenue", "income", 50_000)])
        await append_job(db, job)
        await kilitle(db, org, "2026-01", uid)
        await db.commit()
    assert (await _patch(client, h, t1, "rent")).json()["data"]["ledger"] == "booked_in_open_month"

    async def by_cat(a, b):
        async with client._maker() as db:
            view = await company_rows(db, org, Period(a, b))
        out: dict[str, int] = {}
        for r in view.profit:
            out[r.category] = out.get(r.category, 0) + r.amount_cents
        return out, view

    jan, jan_view = await by_cat("2026-01", "2026-01")
    feb, feb_view = await by_cat("2026-02", "2026-02")
    both, both_view = await by_cat("2026-01", "2026-02")
    assert jan == {"other_expense": 10_000}                       # the closed month, as it was
    assert feb == {"other_expense": -10_000, "rent": 10_000}      # the pair, booked in February
    assert both == {"other_expense": 0, "rent": 10_000}           # together: the corrected books
    assert feb_view.cash == [] and feb_view.rows == 0 and feb_view.months == []   # not money, not a month
    assert jan_view.rows == both_view.rows == 1
    async with client._maker() as db:
        assert (await ledger_summary(db, org, Period("2026-01", "2026-02")))["expense_cents"] == 10_000
        assert (await ledger_summary(db, org, Period("2026-02", "2026-02")))["expense_cents"] == 0


@pytest.mark.asyncio
async def test_a_late_item_counts_in_the_open_month_it_was_written_into(client):
    _h, org, uid = await _org(client, "p10@x.com")
    async with client._maker() as db:
        first, _ = await _job(db, org, uid, [((2026, 1, 15), "revenue", "income", 10_000)])
        await append_job(db, first)
        await kilitle(db, org, "2026-01", uid)
        await db.commit()
        late, _ = await _job(db, org, uid, [((2026, 1, 20), "revenue", "income", 7_000)])
        await append_job(db, late)
        assert len([r for r in await _ledger(db, org) if r.asil_donem == "2026-01"]) == 1
        jan = await ledger_summary(db, org, Period("2026-01", "2026-01"))
        feb = await ledger_summary(db, org, Period("2026-02", "2026-02"))
        both = await ledger_summary(db, org, Period("2026-01", "2026-02"))
    assert (jan["revenue_cents"], feb["revenue_cents"], both["revenue_cents"]) == (10_000, 7_000, 17_000)


@pytest.mark.asyncio
async def test_the_company_view_reads_the_default_period_and_names_it(client):
    _h, org, *_ = await _appended(client, "p11@x.com", _thirteen())
    async with client._maker() as db:
        view = await ledger_view(db, org)
        everything = await ledger_view(db, org, Period("2025-01", "2026-01"))
    assert view is not None and everything is not None
    assert view.period["months"] == 12 and view.period["label"] == "2025-02 – 2026-01"
    assert len(view.profit) == 12 and len(everything.profit) == 13
    assert view.signature != everything.signature
