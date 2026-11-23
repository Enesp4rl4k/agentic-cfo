"""An open-banking window wider than the account's history must not dilute what reads the months (PR #124 item 4).

#126 fixed where the pull's coverage starts. This pins the consumers: the materiality threshold (`usable_months`,
only months with an outflow) and the runway's burn read the same coverage, so the empty months before the account
existed are neither "complete" nor averaged in. Figures written by hand: 1.600,00 out every month the account existed.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest_asyncio

from app.models.canonical_transaction import CanonicalTransaction
from app.services import materiality as m
from app.services.coverage import annotate_series, apply_period, usable_months
from app.services.ingest.feed import pull_coverage
from app.services.pull_coverage import period_from_feed
from app.services.runway import RUNWAY_MIN_MONTHS, compute_runway
from tests.api_helpers import bellek_istemcisi, kullanici

LIRA = 100
OUT = 1_600 * LIRA
OPENING = {"balance_cents": 8_000_000, "as_of": "2026-06-05", "age_days": 1, "stale": False, "filename": "e.csv"}


@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


def _first_of(months_back: int) -> datetime:
    now = datetime.now(UTC)
    year, month = now.year, now.month - months_back
    while month < 1:
        year, month = year - 1, month + 12
    return datetime(year, month, 1, tzinfo=UTC)


def _young_account_extent(real_months: int) -> dict:
    """What a 14-month pull of an account that existed `real_months` complete months yields (`pull_coverage` -> period)."""
    start = _first_of(real_months)
    end = datetime.now(UTC).replace(day=1) - timedelta(days=1)
    window = (_first_of(14).date().isoformat(), end.date().isoformat())
    days = [start.date().isoformat(), end.date().isoformat()]
    cov = pull_coverage(window, days, None, opened_on=start.date().isoformat())
    assert cov is not None and cov["covered_from"] == start.date().isoformat()
    extent = apply_period({"start": days[0], "end": days[1]}, period_from_feed({"feed": {"source": "open_banking", "pull_coverage": cov}}))
    assert extent is not None
    return extent


async def test_the_materiality_threshold_is_the_real_burn_not_a_diluted_one(client, monkeypatch) -> None:
    _, org_id, _ = await kullanici(client, "pencere@example.com", role="owner")
    real = 4
    async with client._maker() as db:
        for back in range(1, real + 1):
            db.add(CanonicalTransaction(
                org_id=org_id, source_type="bank_statement", source_record_id=f"out-{back}",
                transaction_date=_first_of(back).replace(day=15), amount_cents=OUT, currency="TRY",
                direction="expense", basis="cash",
            ))
        await db.commit()
    extent = _young_account_extent(real)

    async def proven(db, org_id, currency=None):
        return [extent]

    monkeypatch.setattr("app.services.bank_accounts.proven_statements", proven)
    async with client._maker() as db:
        got, found = await m.measure_monthly_outflow(db, org_id)
    # Ten empty months precede the account: none is a complete month and none is averaged in.
    assert got is not None and found == real and len(got["months"]) == real
    assert got["avg_cents"] == OUT and min(got["months"]) >= _first_of(real).strftime("%Y-%m")


def test_the_empty_months_before_the_account_are_not_usable_months_for_any_consumer() -> None:
    extent = _young_account_extent(2)
    months = [_first_of(b).strftime("%Y-%m") for b in range(14, 0, -1)]
    series = annotate_series(
        [{"month": mo, "in": 0, "out": OUT if i >= 12 else 0, "net": -OUT if i >= 12 else 0} for i, mo in enumerate(months)],
        [], [extent],
    )
    usable = usable_months(series)
    assert [u["month"] for u in usable] == months[-2:]
    block = compute_runway(OPENING, {"monthly_series": series}, "TRY")
    assert block["status"] == "insufficient_history" and block["months_used"] == 2 < RUNWAY_MIN_MONTHS
    assert block["runway_months"] is None
