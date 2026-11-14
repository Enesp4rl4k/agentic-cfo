"""Plan v10 O5 foundation: the radar's forecast is kept, as it was made, on the day it was made.

Grading the 4-week forecast (O5) needs the forecast from 4 weeks ago. Recomputing it now
would use what is known now: hindsight, not a forecast. So the radar is written down each
day, and only a radar anchored on the day it is computed counts as a forecast.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.models.cash_radar_snapshot import CashRadarSnapshot
from app.models.open_item import OpenItem
from app.services.cash_radar import compute_cash_radar
from app.services.radar_forecast_log import (
    forecast_for_target,
    record_daily_forecasts,
    record_forecast,
)
from tests.api_helpers import bellek_istemcisi, kullanici
from tests.radar_helpers import statement, upload

TODAY = date(2025, 2, 3)


@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


async def _company_with_balance(client, email: str) -> tuple[dict, str]:
    headers, org_id, _ = await kullanici(client, email)
    await upload(
        client,
        org_id,
        {"amount_cents": 50_000_00, "transaction_date": "2025-01-31", "type": "income"},
        meta=statement("2025-01-31", 50_000_00),
    )
    return headers, org_id


async def _count(client, org_id: str) -> int:
    async with client._maker() as db:
        return (
            await db.execute(
                select(func.count())
                .select_from(CashRadarSnapshot)
                .where(CashRadarSnapshot.org_id == org_id)
            )
        ).scalar_one()


@pytest.mark.asyncio
async def test_the_same_forecast_is_written_once(client):
    _, org_id = await _company_with_balance(client, "a@forecast-log.com")
    async with client._maker() as db:
        radar = await compute_cash_radar(db, org_id, anchor_date=TODAY)
        first = await record_forecast(db, org_id, radar, today=TODAY)
        second = await record_forecast(db, org_id, radar, today=TODAY)
        await db.commit()
    assert first is not None
    assert second is not None
    assert first.id == second.id
    assert await _count(client, org_id) == 1


@pytest.mark.asyncio
async def test_a_radar_for_a_past_day_is_hindsight_and_is_not_written(client):
    _, org_id = await _company_with_balance(client, "b@forecast-log.com")
    async with client._maker() as db:
        radar = await compute_cash_radar(db, org_id, anchor_date=TODAY - timedelta(days=28))
        assert await record_forecast(db, org_id, radar, today=TODAY) is None
        await db.commit()
    assert await _count(client, org_id) == 0


@pytest.mark.asyncio
async def test_a_changed_forecast_is_appended_and_the_old_one_kept(client):
    _, org_id = await _company_with_balance(client, "c@forecast-log.com")
    async with client._maker() as db:
        before = await record_forecast(
            db, org_id, await compute_cash_radar(db, org_id, anchor_date=TODAY), today=TODAY
        )
        db.add(
            OpenItem(
                org_id=org_id,
                direction="payable",
                document_id="P-1",
                counterparty="Tedarikçi",
                amount_cents=10_000_00,
                issue_date=date(2025, 1, 20),
                due_date=date(2025, 2, 5),
            )
        )
        await db.flush()
        after = await record_forecast(
            db, org_id, await compute_cash_radar(db, org_id, anchor_date=TODAY), today=TODAY
        )
        await db.commit()
    assert before is not None
    assert after is not None
    assert before.id != after.id
    assert await _count(client, org_id) == 2
    assert before.snapshot_json["weeks"][0]["end_balance_cents"] == 50_000_00
    assert after.snapshot_json["weeks"][0]["end_balance_cents"] == 40_000_00


@pytest.mark.asyncio
async def test_a_written_forecast_cannot_be_rewritten(client):
    _, org_id = await _company_with_balance(client, "d@forecast-log.com")
    async with client._maker() as db:
        snap = await record_forecast(
            db, org_id, await compute_cash_radar(db, org_id, anchor_date=TODAY), today=TODAY
        )
        await db.commit()
        assert snap is not None
        snap.snapshot_json = {"weeks": []}
        with pytest.raises(ValueError, match="immutable"):
            await db.flush()


@pytest.mark.asyncio
async def test_the_four_week_forecast_for_a_day_is_found(client):
    _, org_id = await _company_with_balance(client, "e@forecast-log.com")
    async with client._maker() as db:
        await record_forecast(
            db, org_id, await compute_cash_radar(db, org_id, anchor_date=TODAY), today=TODAY
        )
        await db.commit()
        # Week 4 runs TODAY+21 .. TODAY+27; its end balance is the forecast for TODAY+27.
        found = await forecast_for_target(db, org_id, target=TODAY + timedelta(days=27), weeks=4)
        missing = await forecast_for_target(db, org_id, target=TODAY + timedelta(days=26), weeks=4)
    assert found is not None
    assert found.anchor_date == TODAY.isoformat()
    assert found.end_balance_cents == 50_000_00
    assert missing is None


@pytest.mark.asyncio
async def test_opening_the_radar_today_writes_the_forecast(client):
    headers, org_id = await _company_with_balance(client, "f@forecast-log.com")
    r = await client.get("/api/v1/ledger/cash-radar", headers=headers)
    assert r.status_code == 200, r.text
    assert await _count(client, org_id) == 1
    # Looking at a past day changes nothing in the log.
    r = await client.get("/api/v1/ledger/cash-radar?anchor_date=2025-01-01", headers=headers)
    assert r.status_code == 200, r.text
    assert await _count(client, org_id) == 1


@pytest.mark.asyncio
async def test_the_daily_job_writes_a_forecast_only_for_companies_it_knows_something_about(client):
    _, known = await _company_with_balance(client, "g@forecast-log.com")
    _, empty, _ = await kullanici(client, "h@forecast-log.com")
    async with client._maker() as db:
        written = await record_daily_forecasts(db, today=datetime.now(UTC).date())
        await db.commit()
    assert written >= 1
    assert await _count(client, known) == 1
    assert await _count(client, empty) == 0


def test_the_scheduler_registers_the_daily_forecast_log():
    from app.scheduler import get_scheduler

    assert get_scheduler().get_job("radar_forecast_log") is not None
