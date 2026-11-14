"""O4 review fixes — the Monday briefing may not state what it does not know.

Each test is a case found by reading and probing the first version.
"""

from __future__ import annotations

from datetime import date

import pytest_asyncio
from sqlalchemy import func, select

from app.core.turkish import contains
from app.models.decision_log import DecisionLog
from app.models.open_item import OpenItem
from app.services.monday_briefing import assemble_monday_briefing, verify_narrative_numbers
from tests.api_helpers import bellek_istemcisi, kullanici
from tests.test_monday_briefing import _statement, _upload

ANCHOR = date(2025, 2, 1)


@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


def _payable(org_id: str) -> OpenItem:
    return OpenItem(
        org_id=org_id, direction="payable", document_id="P1", counterparty="Demir Çelik A.Ş.",
        amount_cents=40_000_00, issue_date=date(2025, 1, 15), due_date=date(2025, 2, 4), description="Hammadde",
    )


def _receivable(org_id: str) -> OpenItem:
    return OpenItem(
        org_id=org_id, direction="receivable", document_id="R1", counterparty="Örnek Müşteri Ltd.",
        amount_cents=20_000_00, issue_date=date(2025, 1, 15), due_date=date(2025, 2, 5), description="Proje",
    )


# ── what the briefing says when the bank balance is unknown ────────────────────────────────────

async def test_without_a_known_bank_balance_it_does_not_state_a_balance(client):
    _, org_id, _ = await kullanici(client, "acc-nobal@example.com")
    async with client._maker() as db:
        db.add(_receivable(org_id))
        await db.commit()
        briefing = await assemble_monday_briefing(db, org_id, anchor_date=ANCHOR)

    assert briefing.starting_cash_cents is None
    assert not contains(briefing.sentence_radar, "hafta sonu bakiyesi:")
    assert contains(briefing.sentence_radar, "bilinmiyor")


async def test_without_a_known_balance_it_does_not_reassure(client):
    _, org_id, _ = await kullanici(client, "acc-noreassure@example.com")
    async with client._maker() as db:
        db.add(_payable(org_id))
        await db.commit()
        briefing = await assemble_monday_briefing(db, org_id, anchor_date=ANCHOR)
    assert not contains(briefing.sentence_action, "normal seyret")
    assert contains(briefing.sentence_action, "bakiye")


async def test_a_calm_week_still_names_what_the_radar_does_not_count(client):
    _, org_id, _ = await kullanici(client, "acc-notincl@example.com")
    await _upload(client, org_id, meta=_statement("2025-01-31", 500_000_00))
    async with client._maker() as db:
        briefing = await assemble_monday_briefing(db, org_id, anchor_date=ANCHOR)
    assert contains(briefing.sentence_action, "radara dahil değil")


async def test_a_company_with_no_data_has_no_briefing_to_send(client):
    _, org_id, _ = await kullanici(client, "acc-nodata@example.com")
    async with client._maker() as db:
        briefing = await assemble_monday_briefing(db, org_id, anchor_date=ANCHOR)
    assert briefing.has_data is False


async def test_a_company_with_a_balance_has_a_briefing(client):
    _, org_id, _ = await kullanici(client, "acc-data@example.com")
    await _upload(client, org_id, meta=_statement("2025-01-31", 10_000_00))
    async with client._maker() as db:
        briefing = await assemble_monday_briefing(db, org_id, anchor_date=ANCHOR)
    assert briefing.has_data is True


# ── the gate ─────────────────────────────────────────────────────────────────────────────────

def test_a_figure_a_little_off_is_still_invented():
    # 289.000 is 1.4% from 285.000: close is not true.
    assert verify_narrative_numbers("Alacağınız 289.000 TL.", {285_000_00}) is False


def test_the_exact_figure_passes_even_if_written_without_kurus():
    assert verify_narrative_numbers("Alacağınız 285.000 TL.", {285_000_00}) is True
    assert verify_narrative_numbers("Alacağınız 285.000,37 TL.", {285_000_37}) is True


def test_a_number_that_is_not_money_is_checked_too():
    # "37 gün" and "4 fatura" are claims about the company that nothing here supports.
    assert verify_narrative_numbers("Müşteri 37 gün gecikmiş.", {285_000_00}) is False
    assert verify_narrative_numbers("4 fatura açık.", {285_000_00}) is False


def test_a_percentage_nobody_computed_is_rejected():
    assert verify_narrative_numbers("Nakit %12 artacak.", {285_000_00}) is False


def test_dates_of_the_briefing_itself_are_allowed():
    assert verify_narrative_numbers(
        "4 Şubat 2025 vadeli 40.000 TL.", {40_000_00}, allowed_plain={4, 2, 2025}
    ) is True


# ── the response is one decision per briefing ────────────────────────────────────────────────

async def test_answering_twice_is_one_decision_not_two(client):
    headers, org_id, _ = await kullanici(client, "acc-twice@example.com")
    await _upload(client, org_id, meta=_statement("2025-01-31", 80_000_00))
    body = {"response": "deferred", "anchor_date": "2025-02-01"}
    first = await client.post("/api/v1/briefing/monday/respond", headers=headers, json=body)
    again = await client.post("/api/v1/briefing/monday/respond", headers=headers, json=body)
    assert first.status_code == again.status_code == 200
    assert first.json()["data"]["decision_id"] == again.json()["data"]["decision_id"]

    async with client._maker() as db:
        n = (await db.execute(select(func.count()).select_from(DecisionLog).where(DecisionLog.org_id == org_id))).scalar()
    assert n == 1


async def test_a_later_answer_replaces_the_earlier_one(client):
    headers, org_id, _ = await kullanici(client, "acc-change@example.com")
    await _upload(client, org_id, meta=_statement("2025-01-31", 80_000_00))
    base = {"anchor_date": "2025-02-01"}
    first = await client.post("/api/v1/briefing/monday/respond", headers=headers, json={**base, "response": "deferred"})
    assert first.json()["data"]["status"] == "open"
    done = await client.post("/api/v1/briefing/monday/respond", headers=headers, json={**base, "response": "done"})
    assert done.json()["data"]["status"] == "closed"
    assert done.json()["data"]["chosen_option_label"] == "Yaptım"
    async with client._maker() as db:
        row = await db.get(DecisionLog, first.json()["data"]["decision_id"])
        assert row.chosen_option_label == "Yaptım" and row.status == "closed"


async def test_an_answer_needs_an_analysis_to_hang_on(client):
    headers, org_id, _ = await kullanici(client, "acc-nojob@example.com")
    res = await client.post("/api/v1/briefing/monday/respond", headers=headers,
                            json={"response": "done", "anchor_date": "2025-02-01"})
    assert res.status_code == 409
    async with client._maker() as db:
        n = (await db.execute(select(func.count()).select_from(DecisionLog).where(DecisionLog.org_id == org_id))).scalar()
    assert n == 0
