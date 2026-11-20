"""G15/G7 review fixes — what the radar projects must not invent money or dates.

Each test is a case found by probing the first version of the recurring-payment
detector and the tax calendar.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest_asyncio

from app.models.canonical_transaction import CanonicalTransaction
from app.models.open_item import OpenItem
from app.models.open_item_match import OpenItemMatch
from app.services.recurring_obligations import (
    detect_recurring_obligations,
    project_recurring_obligations,
)
from app.services.tax_calendar import project_tax_obligations
from tests.api_helpers import bellek_istemcisi


@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


def _cash(org: str, n: int, day: tuple[int, int, int], cents: int, cp: str | None, desc: str):
    return CanonicalTransaction(
        org_id=org, source_type="t", source_record_id=f"{org}-{n}",
        transaction_date=datetime(*day, tzinfo=UTC), amount_cents=cents, currency="TRY",
        direction="expense", category="x", counterparty=cp, description=desc, confidence=90,
        ledger_status="active", basis="cash",
    )


async def _tax(client, org, rows, anchor):
    async with client._maker() as db:
        db.add_all(rows)
        await db.commit()
        return await project_tax_obligations(db, org, anchor, 13)


async def test_the_february_provisional_tax_for_q4_is_in_the_radar_in_january_and_february(client):
    org = "acc-1"
    rows = [_cash(org, i, (2025, m, 17), 500_000, "GIB", "VERGI DAIRESI GECICI VERGI") for i, m in enumerate((5, 8, 11))]
    out = await _tax(client, org, rows, date(2026, 2, 2))
    assert [(p.tax_type, p.expected_date) for p in out if p.tax_type == "gecici_vergi"] == [
        ("gecici_vergi", date(2026, 2, 17))
    ]


async def test_the_next_years_february_one_is_not_projected_a_year_early(client):
    org = "acc-1b"
    rows = [_cash(org, 1, (2025, 11, 17), 500_000, "GIB", "VERGI DAIRESI GECICI VERGI")]
    out = await _tax(client, org, rows, date(2025, 12, 1))
    assert [p.expected_date for p in out if p.tax_type == "gecici_vergi"] == [date(2026, 2, 17)]


async def test_a_supplier_payment_that_says_kdv_included_is_not_a_tax_payment(client):
    org = "acc-2"
    out = await _tax(client, org, [_cash(org, 1, (2025, 1, 10), 1_200_000, "Zeta Tekstil", "Fatura bedeli KDV dahil")],
                     date(2025, 2, 1))
    assert [p for p in out if p.tax_type == "kdv"] == []


async def test_an_insurance_premium_is_not_an_sgk_payment(client):
    org = "acc-2b"
    out = await _tax(client, org, [_cash(org, 1, (2025, 1, 10), 900_000, "Anadolu Sigorta", "Arac sigorta primi")],
                     date(2025, 2, 1))
    assert [p for p in out if p.tax_type == "sgk"] == []


async def test_a_payment_to_the_tax_office_still_counts(client):
    org = "acc-2c"
    out = await _tax(client, org, [_cash(org, 1, (2025, 1, 28), 1_800_000, None, "VERGI DAIRESI KDV ODEMESI")],
                     date(2025, 2, 1))
    assert any(p.tax_type == "kdv" for p in out)


async def test_a_due_date_on_a_weekend_moves_to_the_next_working_day(client):
    org = "acc-3"
    rows = [_cash(org, 1, (2025, 8, 28), 1_800_000, None, "GIB KDV BEYANNAME ODEMESI")]
    out = await _tax(client, org, rows, date(2025, 9, 1))
    kdv = [p.expected_date for p in out if p.tax_type == "kdv"]
    assert date(2025, 9, 28) not in kdv          # a Sunday
    assert date(2025, 9, 29) in kdv
    assert all(d.weekday() < 5 for d in kdv)


async def test_a_rent_that_stopped_is_not_projected_forever(client):
    org = "acc-4"
    async with client._maker() as db:
        db.add_all(_cash(org, i, (2024, m, 5), 2_500_000, "Emlak Ltd", "Kira ofis") for i, m in enumerate((1, 2, 3)))
        await db.commit()
        found = await detect_recurring_obligations(db, org)
    assert project_recurring_obligations(found, date(2025, 2, 1), 13) == []


async def test_a_rent_still_being_paid_is_projected(client):
    org = "acc-4b"
    async with client._maker() as db:
        db.add_all(_cash(org, i, (2025, m, 5), 2_500_000, "Emlak Ltd", "Kira ofis") for i, m in enumerate((10, 11, 12)))
        await db.commit()
        found = await detect_recurring_obligations(db, org)
    assert len(project_recurring_obligations(found, date(2026, 1, 2), 13)) >= 2


async def test_payments_that_vary_a_lot_are_purchases_not_a_recurring_obligation(client):
    org = "acc-5"
    amounts = ((1, 100_000), (2, 5_000_000), (3, 700_000))
    async with client._maker() as db:
        db.add_all(_cash(org, i, (2025, m, 9), c, "Zeta Tekstil", "hammadde alimi") for i, (m, c) in enumerate(amounts))
        await db.commit()
        assert await detect_recurring_obligations(db, org) == []


async def test_a_rent_increase_does_not_hide_the_obligation(client):
    org = "acc-5b"
    amounts = ((7, 2_000_000), (8, 2_000_000), (9, 2_500_000), (10, 2_500_000), (11, 2_500_000))
    async with client._maker() as db:
        db.add_all(_cash(org, i, (2025, m, 5), c, "Emlak Ltd", "Kira ofis") for i, (m, c) in enumerate(amounts))
        await db.commit()
        found = await detect_recurring_obligations(db, org)
    assert [o.amount_cents for o in found] == [2_500_000]


async def test_payments_that_settled_an_invoice_are_not_also_a_recurring_obligation(client):
    """The invoice is already an open item; projecting its payments again would count it twice."""
    org = "acc-6"
    rows = [_cash(org, i, (2025, m, 9), 700_000, "Zeta Tekstil", "aylik hizmet") for i, m in enumerate((9, 10, 11))]
    async with client._maker() as db:
        db.add_all(rows)
        await db.flush()
        item = OpenItem(
            org_id=org, direction="payable", counterparty="Zeta Tekstil", description="e-Fatura Z1",
            amount_cents=2_100_000, paid_cents=2_100_000, currency="TRY", status="settled",
            issue_date=date(2025, 8, 1), document_id="z1",
        )
        db.add(item)
        await db.flush()
        for r in rows:
            db.add(OpenItemMatch(org_id=org, open_item_id=item.id, ledger_row_id=r.id, amount_cents=700_000,
                                 method="invoice_number", status="confirmed", matched_on=date(2025, 11, 9)))
        await db.commit()
        assert await detect_recurring_obligations(db, org) == []
