"""The radar's weekly figures are in one currency: a TRY rent or a TRY tax payment is never added to a USD
week (the opening balance is per currency in `bank_accounts`, tested there). What is left out is reported on its own line, per currency."""
from __future__ import annotations

from datetime import UTC, date, datetime

import pytest_asyncio

from app.models.organization import Organization
from app.services.cash_radar import compute_cash_radar
from tests.api_helpers import bellek_istemcisi, kullanici
from tests.radar_helpers import upload

ANCHOR = date(2025, 2, 1)


@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


def _statement(day: str, cents: int, currency: str | None) -> dict:
    closing = {"date": day, "balance_cents": cents}
    if currency is not None:
        closing["currency"] = currency
    return {"closing_balance": closing}


async def _confirm(client, org_id: str, code: str) -> None:
    async with client._maker() as db:
        org = await db.get(Organization, org_id)
        org.base_currency, org.base_currency_confirmed_at = code, datetime.now(UTC)
        await db.commit()


async def _try_history(client, org_id: str) -> None:
    rent = [
        {"amount_cents": 25_000_00, "type": "expense", "category": "rent", "currency": "TRY",
         "description": "KİRA ÖDEMESİ - MERKEZ OFİS", "counterparty": "Mal Sahibi A.Ş.", "transaction_date": day}
        for day in ("2024-11-05", "2024-12-05", "2025-01-05")
    ]
    tax = {"amount_cents": 18_000_00, "type": "expense", "category": "tax", "currency": "TRY",
           "description": "GİB KDV BEYANNAME ÖDEMESİ", "transaction_date": "2024-12-28"}
    await upload(client, org_id, *rent, tax)


async def _radar(client, org_id: str):
    async with client._maker() as db:
        return await compute_cash_radar(db, org_id, anchor_date=ANCHOR)


async def test_try_recurring_and_tax_outflows_stay_out_of_a_usd_week(client):
    _, org_id, _ = await kullanici(client, "karisim1@example.com")
    await _confirm(client, org_id, "USD")
    await _try_history(client, org_id)

    radar = await _radar(client, org_id)

    assert radar.currency == "USD"
    assert all(w.outflow_cents == 0 and not w.payables for w in radar.weeks)
    assert radar.recurring_payables_cents == 0 and radar.tax_obligations_cents == 0
    try_line = next(t for t in radar.other_currency_totals if t["currency"] == "TRY")
    assert try_line["recurring_payable_cents"] == 25_000_00 * 3  # Feb, Mar, Apr rent, in lira, on its own line
    assert try_line["tax_payable_cents"] > 0
    assert any("TRY" in line for line in radar.not_included)


async def test_a_balance_in_the_radars_currency_still_seeds_it(client):
    _, org_id, _ = await kullanici(client, "karisim4@example.com")
    await _confirm(client, org_id, "USD")
    await upload(client, org_id, meta=_statement("2025-01-31", 200_000_00, "usd"))

    radar = await _radar(client, org_id)

    assert radar.starting_cash_cents == 200_000_00
