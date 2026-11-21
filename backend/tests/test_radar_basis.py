"""The radar says how each figure is known: a document, an estimate, or a placement rule.

The arithmetic is unchanged; these tests pin only what is disclosed.
"""

from __future__ import annotations

from datetime import date

import pytest_asyncio

from app.config import get_settings
from app.models.open_item import OpenItem
from app.services.cash_radar import (
    ASSUMED,
    ESTIMATED,
    KNOWN,
    RadarItem,
    _basis_of,
    _split,
    compute_cash_radar,
)
from app.services.monday_briefing import assemble_monday_briefing
from tests.api_helpers import bellek_istemcisi, kullanici
from tests.radar_helpers import statement, upload

ANCHOR = date(2025, 2, 1)


@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


def _row(kind: str, cents: int, description: str, day: str) -> dict:
    return {
        "amount_cents": cents,
        "type": "expense",
        "category": kind,
        "description": description,
        "counterparty": "Karsi Taraf",
        "transaction_date": day,
    }


async def _open_item(client, org_id: str, direction: str, due: date, cents: int, ref: str) -> None:
    async with client._maker() as db:
        db.add(
            OpenItem(
                org_id=org_id,
                direction=direction,
                counterparty="Karsi Taraf",
                document_id=ref,
                amount_cents=cents,
                due_date=due,
                issue_date=date(2025, 1, 2),
                status="open",
                currency="TRY",
            )
        )
        await db.commit()


async def test_a_forty_day_old_balance_is_stale_and_says_how_old(client):
    _, org_id, _ = await kullanici(client, "stale@example.com")
    await upload(client, org_id, meta=statement("2024-12-23", 80_000_00))

    async with client._maker() as db:
        radar = await compute_cash_radar(db, org_id, anchor_date=ANCHOR)

    opening = radar.opening_cash
    assert opening is not None
    assert (opening.as_of, opening.age_days, opening.stale) == ("2024-12-23", 40, True)
    assert opening.stale_after_days == get_settings().radar_balance_stale_after_days == 7
    assert opening.source_filename == "test.csv"
    assert opening.source_job_id
    # The arithmetic still starts from the balance; only its age is disclosed.
    assert radar.starting_cash_cents == opening.balance_cents == 80_000_00


async def test_a_balance_inside_the_threshold_is_fresh_and_no_balance_is_none(client):
    _, org_id, _ = await kullanici(client, "fresh@example.com")
    _, other, _ = await kullanici(client, "nobalance@example.com")
    await upload(client, org_id, meta=statement("2025-01-26", 5_000_00))

    async with client._maker() as db:
        fresh = (await compute_cash_radar(db, org_id, anchor_date=ANCHOR)).opening_cash
        none = (await compute_cash_radar(db, other, anchor_date=ANCHOR)).opening_cash

    assert fresh is not None
    assert (fresh.age_days, fresh.stale) == (6, False)  # 7 is the limit; only older is stale
    assert none is None


async def test_each_kind_of_item_gets_its_basis(client):
    _, org_id, _ = await kullanici(client, "basis@example.com")
    await upload(client, org_id, meta=statement("2025-01-31", 200_000_00))
    await upload(
        client,
        org_id,
        *(_row("rent", 25_000_00, "KIRA ODEMESI MERKEZ OFIS", d) for d in ("2024-11-05", "2024-12-05", "2025-01-05")),
        _row("tax", 18_000_00, "GIB KDV BEYANNAME ODEMESI", "2024-12-28"),
    )
    await _open_item(client, org_id, "receivable", date(2025, 2, 10), 9_000_00, "R1")
    await _open_item(client, org_id, "payable", date(2025, 1, 20), 4_000_00, "P-late")
    await _open_item(client, org_id, "payable", date(2025, 2, 12), 3_000_00, "P-ok")

    async with client._maker() as db:
        radar = await compute_cash_radar(db, org_id, anchor_date=ANCHOR)

    payables = [p for w in radar.weeks for p in w.payables]
    by_reason = {p["basis_reason"]: p for p in payables}

    recurring = by_reason["recurring_median"]
    assert recurring["basis"] == ESTIMATED
    assert recurring["basis_inputs"]["months_observed"] == 3
    assert recurring["basis_inputs"]["median_cents"] == 25_000_00

    tax = by_reason["tax_historical_median"]
    assert tax["basis"] == ESTIMATED
    assert tax["rules_verified"] is False
    assert tax["basis_inputs"]["payments_observed"] == 1
    assert tax["basis_inputs"]["median_cents"] == 18_000_00

    overdue = by_reason["overdue_payable_placed_in_week_1"]
    assert overdue["basis"] == ASSUMED
    assert overdue["basis_inputs"] == {"due_date": "2025-01-20"}

    documented = [p for p in payables if p["basis_reason"] == "document_due_date"]
    assert [p["amount_cents"] for p in documented] == [3_000_00]
    assert documented[0]["basis"] == KNOWN
    assert documented[0]["rules_verified"] is None
    # Non-tax rows never claim a rules verdict.
    assert all(p["rules_verified"] is None for p in payables if p["instrument"] != "tax")

    # A week's split adds up to its total, by basis.
    for week in radar.weeks:
        out = week.outflow_basis
        assert out.known_cents + out.estimated_cents + out.assumed_cents == week.outflow_cents
        inn = week.inflow_basis
        assert inn.known_cents + inn.estimated_cents + inn.assumed_cents == week.inflow_cents
    assert radar.weeks[0].outflow_basis.assumed_cents == 4_000_00


def test_delay_and_plan_change_bases():
    due, anchor = date(2025, 2, 10), ANCHOR
    assert _basis_of(due, True, 0, False, due, anchor) == (KNOWN, "document_due_date", {})
    assert _basis_of(due, True, 14, False, date(2025, 2, 24), anchor) == (
        ESTIMATED,
        "customer_average_delay",
        {"average_delay_days": 14},
    )
    basis, reason, inputs = _basis_of(due, False, 0, True, date(2025, 3, 3), anchor)
    assert (basis, reason) == (ASSUMED, "payment_plan_change_taken_as_date")
    assert inputs == {"document_due_date": "2025-02-10", "planned_date": "2025-03-03"}


def test_split_totals_by_basis():
    def item(cents: int, basis: str) -> RadarItem:
        return RadarItem("i", None, None, cents, None, "2025-02-01", 0, False, basis=basis)

    split = _split([item(5, KNOWN), item(7, ESTIMATED), item(11, ESTIMATED), item(13, ASSUMED)])
    assert (split.known_cents, split.estimated_cents, split.assumed_cents) == (5, 18, 13)


async def test_the_briefing_qualifies_a_stale_balance(client):
    _, org_id, _ = await kullanici(client, "stalebrief@example.com")
    await upload(client, org_id, meta=statement("2024-12-23", 80_000_00))

    async with client._maker() as db:
        briefing = await assemble_monday_briefing(db, org_id, anchor_date=ANCHOR)

    assert briefing.balance_stale and briefing.balance_as_of == "2024-12-23"
    assert "23 Aralık tarihli ekstreye göre, 40 gün önceki bakiye" in briefing.sentence_radar
    assert "yeni ekstre yükleyin" in briefing.sentence_action
    assert "güncel olmayabilecek" in briefing.sentence_action


async def test_the_briefing_does_not_cry_wolf_on_a_fresh_balance(client):
    _, org_id, _ = await kullanici(client, "freshbrief@example.com")
    await upload(client, org_id, meta=statement("2025-01-30", 80_000_00))

    async with client._maker() as db:
        briefing = await assemble_monday_briefing(db, org_id, anchor_date=ANCHOR)

    assert not briefing.balance_stale
    assert "30 Ocak ekstresine göre" in briefing.sentence_radar
    assert "yeni ekstre" not in briefing.full_text
