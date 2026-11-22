"""The company's cash is per account and per currency; one or two balance steps are weak evidence, not none.

PR #120 review, follow-ups 1 and 2 (the fewer-than-3-steps rule, `proven_balance` without a currency or
account filter). Figures written by hand, lira unless said: two banks closing on 80,000.00 and 40,000.00,
a burn of 30,000.00 a month over January-March 2026.
"""
from __future__ import annotations

from datetime import date
from typing import Any

import pytest_asyncio

from app.services.bank_accounts import proven_balances
from app.services.bank_balance import assess
from app.services.cash_radar import compute_cash_radar
from tests.api_helpers import bellek_istemcisi, kullanici
from tests.radar_helpers import BURN, upload
from tests.radar_helpers import statement_meta as _stmt

ANCHOR = date(2026, 4, 3)
@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


async def _balances(client, org_id: str) -> dict[str, Any]:
    async with client._maker() as db:
        return await proven_balances(db, org_id)


async def _radar(client, org_id: str):
    async with client._maker() as db:
        return await compute_cash_radar(db, org_id, anchor_date=ANCHOR)


async def _two_banks(client, org_id: str) -> None:
    await upload(client, org_id, *BURN, meta=_stmt("2026-01-01", "2026-03-31", 170_000_00, 80_000_00), filename="banka-a.pdf")
    await upload(client, org_id, meta=_stmt("2026-01-01", "2026-03-31", 130_000_00, 40_000_00), filename="banka-b.pdf")


async def test_two_banks_in_one_currency_add_up_and_the_runway_reads_the_same_accounts(client):
    _, org_id, _ = await kullanici(client, "a1@example.com")
    await _two_banks(client, org_id)
    radar = await _radar(client, org_id)
    assert radar.starting_cash_cents == 120_000_00 and radar.opening_cash.basis == "known"
    assert sorted((a["name"], a["balance_cents"]) for a in radar.opening_cash.accounts) == [
        ("banka-a.pdf", 80_000_00), ("banka-b.pdf", 40_000_00),
    ]
    runway = radar.runway
    assert (runway["status"], runway["opening_cash_cents"], runway["runway_months"], runway["level"]) == (
        "computed", 120_000_00, 4.0, "warning"
    )
    assert "2 hesabın son ekstre bakiyelerinin toplamıdır" in runway["message"]


async def test_consecutive_statements_and_the_same_iban_are_one_account_not_two(client):
    _, org_id, _ = await kullanici(client, "a2@example.com")
    await upload(client, org_id, meta=_stmt("2026-01-01", "2026-01-31", 100_000_00, 90_000_00), filename="ocak.pdf")
    await upload(client, org_id, meta=_stmt("2026-02-01", "2026-02-28", 90_000_00, 70_000_00), filename="subat.pdf")
    # March does not open on February's closing balance (a statement is missing) but names the same IBAN.
    await upload(client, org_id, meta=_stmt("2026-03-01", "2026-03-31", 65_000_00, 60_000_00, identity="iban:TR330006100519786457841326"),
                 filename="mart.pdf")
    await upload(client, org_id, meta=_stmt("2026-01-01", "2026-01-31", 1, 2, identity="iban:TR330006100519786457841326"),
                 filename="ocak-ayni-iban.pdf")
    found = await _balances(client, org_id)
    # Jan+Feb chain into one account (70,000); Mar and the Jan statement with the IBAN are one account (60,000).
    assert sorted(a["balance_cents"] for a in found["accounts"]) == [60_000_00, 70_000_00]
    assert found["opening"]["balance_cents"] == 130_000_00


async def test_a_statement_in_another_currency_is_listed_never_added(client):
    _, org_id, _ = await kullanici(client, "a3@example.com")
    await upload(client, org_id, *BURN, meta=_stmt("2026-01-01", "2026-03-31", 170_000_00, 80_000_00), filename="try.pdf")
    await upload(client, org_id, meta=_stmt("2026-01-01", "2026-03-31", 9_000_00, 5_000_00, currency="USD"), filename="usd.pdf")
    radar = await _radar(client, org_id)
    assert radar.currency == "TRY" and radar.starting_cash_cents == 80_000_00
    assert radar.other_currency_balances == [{"currency": "USD", "balance_cents": 5_000_00, "as_of": "2026-03-31", "accounts": 1}]
    # The runway's balance and burn are the lira account's alone: 80,000 over 30,000 a month.
    assert (radar.runway["opening_cash_cents"], radar.runway["runway_months"]) == (80_000_00, 2.7)
    assert [a["currency"] for a in radar.runway["accounts"]] == ["TRY"]


async def test_an_account_whose_latest_balance_is_old_says_its_date(client):
    _, org_id, _ = await kullanici(client, "a4@example.com")
    await _two_banks(client, org_id)
    await upload(client, org_id, meta=_stmt("2025-12-01", "2026-02-10", 30_000_00, 25_000_00), filename="eski-banka.pdf")
    radar = await _radar(client, org_id)
    old = next(a for a in radar.opening_cash.accounts if a["name"] == "eski-banka.pdf")
    assert (old["as_of"], old["behind_days"], old["lagging"]) == ("2026-02-10", 49, True)
    assert radar.starting_cash_cents == 145_000_00
    assert "eski-banka.pdf bakiyesi 10 Şubat 2026 tarihli, diğerlerinden 49 gün eski" in radar.runway["message"]


async def test_an_unverified_account_is_left_out_and_named(client):
    _, org_id, _ = await kullanici(client, "a5@example.com")
    await _two_banks(client, org_id)
    await upload(client, org_id, filename="doğrulanamayan.pdf",
                 meta=_stmt("2026-01-01", "2026-03-31", 1, 999_000_00, basis=None, reason="bakiye zinciri tutmuyor"))
    radar = await _radar(client, org_id)
    assert radar.starting_cash_cents == 120_000_00
    assert radar.unproven_statements == [
        {"job_id": radar.unproven_statements[0]["job_id"], "filename": "doğrulanamayan.pdf", "reason": "bakiye zinciri tutmuyor"}
    ]
    assert "doğrulanamayan.pdf ekstresinin bakiyesi doğrulanamadığı için dışarıda bırakıldı" in radar.runway["message"]


async def test_with_no_proven_account_the_radar_names_the_statement_that_failed(client):
    _, org_id, _ = await kullanici(client, "a6@example.com")
    await upload(client, org_id, filename="bozuk.pdf",
                 meta=_stmt("2026-01-01", "2026-03-31", 1, 2, basis=None, reason="3 satır bekliyor"))
    radar = await _radar(client, org_id)
    assert radar.opening_cash is None and radar.runway["status"] == "no_balance" and radar.runway["runway_months"] is None
    assert "bozuk.pdf ekstresinin bakiyesi doğrulanamadığı için dışarıda bırakıldı (3 satır bekliyor)" in radar.runway["message"]


# ── fewer than three balance steps ──────────────────────────────────────────

def _r(day: str, amount: int, kind: str | None, balance: int | None) -> dict[str, Any]:
    return {"transaction_date": day, "amount_cents": amount, "type": kind, "balance_cents": balance}


UNVERIFIED = {"balance_check": "unverified", "unaccounted": 0}


def test_two_reconciling_steps_are_an_assumption_with_the_reason_stated_never_known():
    rows = [_r("2026-03-02", 10_000, "expense", 90_000), _r("2026-03-05", 5_000, "expense", 85_000),
            _r("2026-03-09", 2_000, "income", 87_000)]
    proof = assess(rows, UNVERIFIED)
    assert (proof["state"], proof["basis"], proof["steps"]) == ("weak", "assumed", 2)
    assert proof["reason"] == "yalnızca 2 bakiye adımıyla doğrulandı"


def test_three_steps_the_reader_would_not_verify_stay_unverified_it_is_not_our_call():
    rows = [_r("2026-03-02", 10_000, "expense", 90_000), _r("2026-03-05", 5_000, "expense", 85_000),
            _r("2026-03-09", 2_000, "income", 87_000), _r("2026-03-10", 1_000, "expense", 86_000)]
    proof = assess(rows, UNVERIFIED)
    assert (proof["state"], proof["basis"]) == ("unverified", None) and "okuyucu" in proof["reason"]


def test_a_thin_chain_that_holds_in_both_file_orders_is_not_evidence():
    both = [_r("2026-03-02", 100, "income", 500), _r("2026-03-05", 100, "expense", 400)]
    proof = assess(both, UNVERIFIED)
    assert proof["basis"] is None and "her iki sıralamada" in proof["reason"]


def test_a_thin_chain_with_a_row_of_unknown_direction_or_a_wrong_amount_is_not_evidence():
    assert assess([_r("2026-03-02", 100, None, 500), _r("2026-03-05", 100, "expense", 400)], UNVERIFIED)["basis"] is None
    assert assess([_r("2026-03-02", 100, "expense", 500), _r("2026-03-05", 150, "expense", 400)], UNVERIFIED)["reason"] == (
        "satır bakiyeleri birbirini tutmuyor"
    )
    assert assess([_r("2026-03-02", 100, "expense", 500)], UNVERIFIED)["basis"] is None  # one row has nothing to chain to


def test_rows_the_readers_lost_make_any_chain_unproven():
    rows = [_r("2026-03-02", 10_000, "expense", 90_000), _r("2026-03-05", 5_000, "expense", 85_000)]
    assert assess(rows, {"balance_check": "verified", "unaccounted": 2})["reason"] == "2 satır hesaba katılamadı"


async def test_a_weak_statement_reaches_the_radar_and_the_runway_as_an_assumption(client):
    _, org_id, _ = await kullanici(client, "a7@example.com")
    await upload(client, org_id, *BURN, filename="kisa.pdf", meta=_stmt(
        "2026-01-01", "2026-03-31", 170_000_00, 80_000_00, basis="assumed", reason="yalnızca 2 bakiye adımıyla doğrulandı"))
    radar = await _radar(client, org_id)
    assert radar.opening_cash.basis == "assumed" and radar.opening_cash.basis_note == "yalnızca 2 bakiye adımıyla doğrulandı"
    assert radar.runway["basis"] == "assumed" and radar.runway["balance_basis"] == "assumed"
    assert "Bakiye zayıf kanıta dayanıyor (yalnızca 2 bakiye adımıyla doğrulandı), varsayım olarak alındı" in radar.runway["message"]
