"""Plan v10 §4 (O3) & Plan v11 Faz 2 — Nakit Radarı: Tekrarlayan ödemeler, vergi/SGK takvimi, çek/senetler ve karar sözleşmesi."""

from __future__ import annotations

from datetime import date

import pytest_asyncio

from app.core.turkish import contains
from app.models.open_item import OpenItem
from app.services.cash_radar import compute_cash_radar
from tests.api_helpers import bellek_istemcisi, kullanici
from tests.radar_helpers import statement as _statement
from tests.radar_helpers import upload as _upload

ANCHOR = date(2025, 2, 1)


@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


async def test_recurring_rent_and_payroll_projected_into_cash_radar(client):
    """Past recurring rent (seen in 3 distinct months) is projected into upcoming radar weeks."""
    _, org_id, _ = await kullanici(client, "recurring_radar@example.com")
    await _upload(client, org_id, meta=_statement("2025-01-31", 200_000_00))

    # Historical rent in 3 distinct months (Nov 2024, Dec 2024, Jan 2025)
    await _upload(
        client,
        org_id,
        *(
            {
                "amount_cents": 25_000_00,
                "type": "expense",
                "category": "rent",
                "description": "KİRA ÖDEMESİ - MERKEZ OFİS",
                "counterparty": "Mal Sahibi A.Ş.",
                "transaction_date": day,
            }
            for day in ("2024-11-05", "2024-12-05", "2025-01-05")
        ),
    )

    async with client._maker() as db:
        radar = await compute_cash_radar(db, org_id, anchor_date=ANCHOR)

    # Rent is projected on Feb 5, Mar 5, Apr 5
    assert radar.recurring_payables_cents > 0
    assert "Kira, maaş gibi düzenli ödemeler" not in radar.not_included

    # Find the radar items with instrument == "recurring"
    recurring_items = [
        item
        for week in radar.weeks
        for item in week.payables
        if item.get("instrument") == "recurring"
    ]
    assert len(recurring_items) >= 2
    assert any(contains(item.get("description"), "kira") for item in recurring_items)


async def test_statutory_tax_calendar_projected_into_cash_radar(client):
    """Historical tax payments cause statutory GİB/SGK deadlines to project into radar weeks."""
    _, org_id, _ = await kullanici(client, "tax_radar@example.com")
    await _upload(client, org_id, meta=_statement("2025-01-31", 150_000_00))

    # Past KDV and SGK payments
    await _upload(
        client,
        org_id,
        {
            "amount_cents": 18_000_00,
            "type": "expense",
            "category": "tax",
            "description": "GİB KDV BEYANNAME ÖDEMESİ",
            "transaction_date": "2024-12-28",
        },
        {
            "amount_cents": 35_000_00,
            "type": "expense",
            "category": "tax",
            "description": "SGK PRİM ÖDEMESİ",
            "transaction_date": "2024-12-31",
        },
    )

    async with client._maker() as db:
        radar = await compute_cash_radar(db, org_id, anchor_date=ANCHOR)

    assert radar.tax_obligations_cents > 0
    assert "Vergi ve SGK yükümlülükleri" not in radar.not_included

    tax_items = [
        item for week in radar.weeks for item in week.payables if item.get("instrument") == "tax"
    ]
    assert len(tax_items) >= 2


async def test_cheques_recognized_and_disclaimer_cleared(client):
    """Cheques and promissory notes in OpenItem are included and remove 'Çek ve senetler' from disclaimer."""
    _, org_id, _ = await kullanici(client, "cheque_radar@example.com")
    await _upload(client, org_id, meta=_statement("2025-01-31", 100_000_00))

    # Add a cheque open item directly
    async with client._maker() as db:
        cheque_item = OpenItem(
            org_id=org_id,
            direction="payable",
            instrument="cheque",
            document_id="CHEQUE-2025-001",
            counterparty="Ana Tedarikçi A.Ş.",
            description="Vadeli Tedarikçi Çeki",
            amount_cents=40_000_00,
            issue_date=date(2025, 1, 15),
            due_date=date(2025, 2, 20),
            status="open",
        )
        db.add(cheque_item)
        await db.commit()

        radar = await compute_cash_radar(db, org_id, anchor_date=ANCHOR)

    assert "Çek ve senetler" not in radar.not_included
    cheque_items = [
        item for week in radar.weeks for item in week.payables if item.get("instrument") == "cheque"
    ]
    assert len(cheque_items) == 1
    assert cheque_items[0]["amount_cents"] == 40_000_00
