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


IBAN_A = "iban:TR330006100519786457841326"
IBAN_B = "iban:TR560006200000000000123456"


async def _two_banks(client, org_id: str) -> None:
    """Two banks that state different account numbers: provably two accounts."""
    await upload(client, org_id, *BURN, meta=_stmt("2026-01-01", "2026-03-31", 170_000_00, 80_000_00, identity=IBAN_A), filename="banka-a.pdf")
    await upload(client, org_id, meta=_stmt("2026-01-01", "2026-03-31", 130_000_00, 40_000_00, identity=IBAN_B), filename="banka-b.pdf")


async def _answer(client, headers, answer: str, found: dict[str, Any], **names: str):
    q = found["questions"][0]
    return await client.post("/api/v1/held-rows/account-questions/answer", headers=headers, json={
        "answer": answer, "job_ids_a": q["job_ids_a"], "job_ids_b": q["job_ids_b"], **names,
    })


async def _decisions(client) -> list[Any]:
    from sqlalchemy import select

    from app.models.decision import Decision

    async with client._maker() as db:
        return list((await db.execute(select(Decision).where(Decision.kind == "account_identity"))).scalars().all())


async def test_two_banks_that_state_different_accounts_add_up_and_the_runway_reads_them(client):
    _, org_id, _ = await kullanici(client, "a1@example.com")
    await _two_banks(client, org_id)
    radar = await _radar(client, org_id)
    assert radar.starting_cash_cents == 120_000_00 and radar.opening_cash.basis == "known"
    assert radar.account_questions == [] and not radar.opening_cash.identity_uncertain
    assert sorted((a["name"], a["balance_cents"]) for a in radar.opening_cash.accounts) == [
        ("banka-a.pdf", 80_000_00), ("banka-b.pdf", 40_000_00),
    ]
    runway = radar.runway
    assert (runway["status"], runway["opening_cash_cents"], runway["runway_months"], runway["level"]) == (
        "computed", 120_000_00, 4.0, "warning"
    )
    assert "2 hesabın son ekstre bakiyelerinin toplamıdır" in runway["message"]


async def test_banks_named_in_the_header_but_with_no_account_number_are_different_banks(client):
    _, org_id, _ = await kullanici(client, "a1b@example.com")
    await upload(client, org_id, meta=_stmt("2026-01-01", "2026-03-31", 1, 80_000_00, identity="bank:garanti"), filename="g.pdf")
    await upload(client, org_id, meta=_stmt("2026-01-01", "2026-03-31", 2, 40_000_00, identity="bank:akbank"), filename="a.pdf")
    found = await _balances(client, org_id)
    assert found["opening"]["balance_cents"] == 120_000_00 and found["opening"]["basis"] == "known" and found["questions"] == []


# The reviewer's three reproductions, with no account number in any file: nothing is added, nothing is known.

async def test_the_same_statement_uploaded_twice_is_counted_once_and_known(client):
    _, org_id, _ = await kullanici(client, "a2@example.com")
    for name in ("q1.pdf", "q1-kopya.pdf"):
        await upload(client, org_id, meta=_stmt("2026-01-01", "2026-03-31", 170_000_00, 80_000_00), filename=name)
    found = await _balances(client, org_id)
    assert found["opening"]["balance_cents"] == 80_000_00 and len(found["accounts"]) == 1
    assert found["opening"]["basis"] == "known" and found["questions"] == []


async def test_january_and_march_with_february_missing_use_the_newest_balance_and_ask(client):
    _, org_id, _ = await kullanici(client, "a3@example.com")
    await upload(client, org_id, meta=_stmt("2026-01-01", "2026-01-31", 100_000_00, 90_000_00), filename="ocak.pdf")
    await upload(client, org_id, meta=_stmt("2026-03-01", "2026-03-31", 70_000_00, 60_000_00), filename="mart.pdf")
    radar = await _radar(client, org_id)
    assert radar.starting_cash_cents == 60_000_00          # never 150,000
    assert radar.opening_cash.basis == "assumed" and radar.opening_cash.identity_uncertain
    assert radar.opening_cash.identity_note == (
        "2 ekstrenin aynı hesaba mı ait olduğu bilinmiyor; yalnızca en güncel bakiye (2026-03-31) kullanıldı"
    )
    assert len(radar.account_questions) == 1
    assert radar.account_questions[0]["question"] == "Bu ekstreler aynı banka hesabına mı ait?"


async def test_q1_and_an_overlapping_statement_with_no_proof_of_sameness_use_the_newest_and_ask(client):
    _, org_id, _ = await kullanici(client, "a4@example.com")
    await upload(client, org_id, meta=_stmt("2026-01-01", "2026-03-31", 170_000_00, 60_000_00), filename="q1.pdf")
    await upload(client, org_id, meta=_stmt("2026-03-15", "2026-04-30", 55_000_00, 50_000_00), filename="mar-nis.pdf")
    found = await _balances(client, org_id)
    assert found["opening"]["balance_cents"] == 50_000_00 and found["opening"]["basis"] == "assumed"
    assert len(found["questions"]) == 1 and found["opening"]["uncertain"]


async def test_an_overlap_where_the_balances_agree_on_the_same_days_is_one_account_joined(client):
    _, org_id, _ = await kullanici(client, "a5@example.com")
    shared = {"2026-03-20": 58_000_00, "2026-03-31": 60_000_00}
    await upload(client, org_id, meta=_stmt("2026-01-01", "2026-03-31", 170_000_00, 60_000_00, points=shared), filename="q1.pdf")
    await upload(client, org_id, meta=_stmt("2026-03-15", "2026-04-30", 55_000_00, 50_000_00,
                                            points={**shared, "2026-04-30": 50_000_00}), filename="mar-nis.pdf")
    found = await _balances(client, org_id)
    assert found["opening"]["balance_cents"] == 50_000_00 and len(found["accounts"]) == 1
    assert found["opening"]["basis"] == "known" and found["questions"] == []
    # A statement that disagrees on a day both show is not this account's: unknown, not added.
    await upload(client, org_id, filename="baska.pdf", meta=_stmt("2026-03-01", "2026-04-10", 1, 7_000_00, points={"2026-03-20": 1_00}))
    again = await _balances(client, org_id)
    assert again["opening"]["balance_cents"] == 50_000_00 and again["opening"]["basis"] == "assumed" and again["questions"]


async def test_an_unanswered_question_caps_the_runway_at_a_warning_and_is_in_the_payload(client):
    headers, org_id, _ = await kullanici(client, "a6@example.com")
    await upload(client, org_id, *BURN, meta=_stmt("2026-01-01", "2026-03-30", 100_000_00, 60_000_00), filename="a.pdf")
    await upload(client, org_id, meta=_stmt("2026-01-02", "2026-03-31", 90_000_00, 50_000_00), filename="b.pdf")
    runway = (await _radar(client, org_id)).runway
    # 50,000 over a 30,000 burn is 1.7 months: critical if the cash were measured. It is not.
    assert runway["runway_months"] == 1.7 and runway["level"] == "warning" and runway["basis"] == "assumed"
    assert runway["identity_uncertain"] and "yalnızca en güncel bakiye" in runway["message"]
    data = (await client.get("/api/v1/held-rows/account-questions", headers=headers)).json()["data"]
    assert data["count"] == 1 and data["can_decide"] is True
    assert {data["questions"][0]["a"]["balance_cents"], data["questions"][0]["b"]["balance_cents"]} == {60_000_00, 50_000_00}


async def test_answering_same_account_merges_names_the_missing_statement_and_is_recorded(client):
    headers, org_id, _ = await kullanici(client, "a7@example.com")
    await upload(client, org_id, *BURN, meta=_stmt("2026-01-01", "2026-01-31", 100_000_00, 90_000_00), filename="ocak.pdf")
    await upload(client, org_id, meta=_stmt("2026-03-01", "2026-03-31", 70_000_00, 60_000_00), filename="mart.pdf")
    found = await _balances(client, org_id)
    res = await _answer(client, headers, "same", found, name_a="Garanti TL", name_b="Garanti TL")
    assert res.status_code == 200 and res.json()["data"]["changed"] is True
    radar = await _radar(client, org_id)
    assert radar.starting_cash_cents == 60_000_00 and radar.opening_cash.basis == "known"
    assert radar.account_questions == [] and [a["name"] for a in radar.opening_cash.accounts] == ["Garanti TL"]
    assert radar.opening_cash.accounts[0]["gaps"] == ["2026-02"]
    assert "Şubat için Garanti TL ekstresi eksik; hesaba katılmadı" in radar.runway["message"]
    assert [(d.outcome, d.decided_via) for d in await _decisions(client)] == [("same", "human")]


async def test_answering_different_accounts_adds_them_and_the_answer_can_be_changed(client):
    headers, org_id, _ = await kullanici(client, "a8@example.com")
    await upload(client, org_id, meta=_stmt("2026-01-01", "2026-01-31", 100_000_00, 90_000_00), filename="ocak.pdf")
    await upload(client, org_id, meta=_stmt("2026-03-01", "2026-03-31", 70_000_00, 60_000_00), filename="mart.pdf")
    assert (await _answer(client, headers, "different", await _balances(client, org_id))).status_code == 200
    radar = await _radar(client, org_id)
    assert radar.starting_cash_cents == 150_000_00 and radar.account_questions == []
    # The January account is 59 days behind March's: the summed cash is as old as its oldest account, so only assumed.
    assert radar.opening_cash.basis == "assumed" and "bakiye 59 gün önceki ekstreye ait (2026-01-31)" in radar.opening_cash.basis_note
    # Reversal: the owner changes the answer; the cash is recomputed and the first decision is superseded, not erased.
    accounts = (await _balances(client, org_id))["accounts"]
    ids = {a["name"]: a["job_id"] for a in accounts}
    res = await client.post("/api/v1/held-rows/account-questions/answer", headers=headers,
                            json={"answer": "same", "job_ids_a": [ids["ocak.pdf"]], "job_ids_b": [ids["mart.pdf"]]})
    assert res.status_code == 200
    assert (await _radar(client, org_id)).starting_cash_cents == 60_000_00
    rows = await _decisions(client)
    assert sorted(d.outcome for d in rows) == ["different", "same"]
    assert next(d for d in rows if d.outcome == "same").supersedes_id == next(d for d in rows if d.outcome == "different").id


async def test_only_an_owner_or_admin_may_answer(client):
    headers, org_id, _ = await kullanici(client, "a9@example.com", role="analyst")
    await upload(client, org_id, meta=_stmt("2026-01-01", "2026-01-31", 100_000_00, 90_000_00), filename="ocak.pdf")
    await upload(client, org_id, meta=_stmt("2026-03-01", "2026-03-31", 70_000_00, 60_000_00), filename="mart.pdf")
    found = await _balances(client, org_id)
    assert (await _answer(client, headers, "same", found)).status_code == 403
    listed = (await client.get("/api/v1/held-rows/account-questions", headers=headers)).json()["data"]
    assert listed["count"] == 1 and listed["can_decide"] is False
    assert (await _radar(client, org_id)).starting_cash_cents == 60_000_00 and await _decisions(client) == []


async def test_another_companys_statements_cannot_be_answered_about(client):
    headers, _, _ = await kullanici(client, "a10@example.com")
    _, other_org, _ = await kullanici(client, "a11@example.com")
    first = await upload(client, other_org, meta=_stmt("2026-01-01", "2026-01-31", 1, 2), filename="x.pdf")
    second = await upload(client, other_org, meta=_stmt("2026-03-01", "2026-03-31", 3, 4), filename="y.pdf")
    res = await client.post("/api/v1/held-rows/account-questions/answer", headers=headers,
                            json={"answer": "same", "job_ids_a": [first], "job_ids_b": [second]})
    assert res.status_code == 422


async def test_uncertainty_is_decided_per_currency_and_a_foreign_statement_is_never_asked_about(client):
    _, org_id, _ = await kullanici(client, "a12@example.com")
    await upload(client, org_id, *BURN, meta=_stmt("2026-01-01", "2026-01-31", 100_000_00, 90_000_00), filename="ocak.pdf")
    await upload(client, org_id, meta=_stmt("2026-03-01", "2026-03-31", 70_000_00, 60_000_00), filename="mart.pdf")
    await upload(client, org_id, meta=_stmt("2026-03-01", "2026-03-31", 9_000_00, 5_000_00, currency="USD"), filename="usd.pdf")
    radar = await _radar(client, org_id)
    assert radar.starting_cash_cents == 60_000_00 and len(radar.account_questions) == 1
    assert radar.other_currency_balances == [{"currency": "USD", "balance_cents": 5_000_00, "as_of": "2026-03-31", "accounts": 1}]


async def test_a_statement_in_another_currency_is_listed_never_added(client):
    _, org_id, _ = await kullanici(client, "a3x@example.com")
    await upload(client, org_id, *BURN, meta=_stmt("2026-01-01", "2026-03-31", 170_000_00, 80_000_00), filename="try.pdf")
    await upload(client, org_id, meta=_stmt("2026-01-01", "2026-03-31", 9_000_00, 5_000_00, currency="USD"), filename="usd.pdf")
    radar = await _radar(client, org_id)
    assert radar.currency == "TRY" and radar.starting_cash_cents == 80_000_00
    assert radar.other_currency_balances == [{"currency": "USD", "balance_cents": 5_000_00, "as_of": "2026-03-31", "accounts": 1}]
    assert (radar.runway["opening_cash_cents"], radar.runway["runway_months"]) == (80_000_00, 2.7)
    assert [a["currency"] for a in radar.runway["accounts"]] == ["TRY"] and radar.account_questions == []


async def test_an_account_whose_latest_balance_is_old_says_its_date(client):
    _, org_id, _ = await kullanici(client, "a4x@example.com")
    await _two_banks(client, org_id)
    await upload(client, org_id, meta=_stmt("2025-12-01", "2026-02-10", 30_000_00, 25_000_00, identity="iban:TR000000000000000000000001"),
                 filename="eski-banka.pdf")
    radar = await _radar(client, org_id)
    old = next(a for a in radar.opening_cash.accounts if a["name"] == "eski-banka.pdf")
    assert (old["as_of"], old["behind_days"], old["lagging"]) == ("2026-02-10", 49, True)
    assert radar.starting_cash_cents == 145_000_00
    assert "eski-banka.pdf bakiyesi 10 Şubat 2026 tarihli, diğerlerinden 49 gün eski" in radar.runway["message"]


async def test_an_unverified_account_is_left_out_and_named(client):
    _, org_id, _ = await kullanici(client, "a5x@example.com")
    await _two_banks(client, org_id)
    await upload(client, org_id, filename="doğrulanamayan.pdf",
                 meta=_stmt("2026-01-01", "2026-03-31", 1, 999_000_00, basis=None, reason="bakiye zinciri tutmuyor"))
    radar = await _radar(client, org_id)
    assert radar.starting_cash_cents == 120_000_00
    assert [(u["filename"], u["reason"]) for u in radar.unproven_statements] == [("doğrulanamayan.pdf", "bakiye zinciri tutmuyor")]
    assert "doğrulanamayan.pdf ekstresinin bakiyesi doğrulanamadığı için dışarıda bırakıldı" in radar.runway["message"]


async def test_with_no_proven_account_the_radar_names_the_statement_that_failed(client):
    _, org_id, _ = await kullanici(client, "a6x@example.com")
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
