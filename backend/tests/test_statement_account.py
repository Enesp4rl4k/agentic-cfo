"""Account identity is read only where a statement speaks about itself: its header, or a column that names it.

PR #125 review: `statement_identity` scanned the first 4000 characters of the raw text, so a counterparty's IBAN
in "FAST TR33... Ali", "Hesap No: 12345678 aidat" or "Akbank EFT" in a row made two statements of ONE account
look like two accounts, and two accounts are added together. Figures written by hand, lira.
"""
from __future__ import annotations

import pytest_asyncio

from app.services.bank_accounts import proven_balances
from app.services.bank_balance import assess
from app.services.statement_account import account_identity, kind, mask
from tests.api_helpers import bellek_istemcisi, kullanici
from tests.radar_helpers import statement_meta, upload

OWN = "TR33 0006 1005 1978 6457 8413 26"
OTHER = "TR56 0006 2000 0000 0000 1234 56"
COLUMNS = "Tarih;Açıklama;Tutar;Bakiye"


@pytest_asyncio.fixture
async def client():
    async with bellek_istemcisi() as c:
        yield c


def _file(header: str, *rows: str) -> str:
    return "\n".join([header, COLUMNS, *rows]) + "\n"


def test_an_iban_in_the_header_is_the_accounts_identity():
    assert account_identity(_file(f"Garanti BBVA\nIBAN: {OWN}", "02.03.2026;Kira;-100,00;900,00")) == "iban:TR330006100519786457841326"


def test_an_account_number_needs_its_label_and_a_bank_counts_only_in_the_header():
    assert account_identity(_file("Hesap No: 1234 5678\nAkbank", "02.03.2026;Kira;-1,00;9,00")) == "acct:12345678"
    assert account_identity(_file("Akbank Hesap Özeti", "02.03.2026;Kira;-1,00;9,00")) == "bank:akbank"
    assert account_identity(_file("Hesap Özeti 12345678", "02.03.2026;Kira;-1,00;9,00")) is None  # a bare number is no account number


def test_nothing_in_a_transaction_row_is_an_identity():
    rows = (
        f"02.03.2026;FAST {OTHER} Ali;-100,00;900,00",
        "03.03.2026;Hesap No: 12345678 aidat;-100,00;800,00",
        "04.03.2026;Gelen havale Akbank EFT;100,00;900,00",
    )
    assert account_identity(_file("Hesap Özeti", *rows)) is None
    assert account_identity("\n".join(rows) + "\n") is None  # no table header: no identity read at all


def test_a_header_naming_two_accounts_states_none():
    assert account_identity(_file(f"IBAN {OWN}\nKarşı IBAN {OTHER}", "02.03.2026;Kira;-1,00;9,00")) is None


def test_a_column_that_names_the_account_counts_only_when_every_row_agrees():
    same = f"Tarih;Açıklama;Tutar;Bakiye;IBAN\n02.03.2026;Kira;-1,00;9,00;{OWN}\n03.03.2026;Su;-1,00;8,00;{OWN}\n"
    assert account_identity(same) == "iban:TR330006100519786457841326"
    mixed = f"Tarih;Açıklama;Tutar;Bakiye;IBAN\n02.03.2026;Kira;-1,00;9,00;{OWN}\n03.03.2026;Su;-1,00;8,00;{OTHER}\n"
    assert account_identity(mixed) is None


def test_an_identifier_is_shown_masked():
    assert mask("iban:TR330006100519786457841326") == "IBAN ****1326"
    assert mask("acct:12345678") == "Hesap ****5678" and mask("bank:akbank") == "akbank" and mask(None) is None
    assert kind("iban:TR33") == "iban" and kind(None) is None


# ── what the evidence does to the cash ───────────────────────────────────────────────────────────

async def _pair(client, first: str, second: str, tag: str):
    _, org_id, _ = await kullanici(client, f"{tag}@example.com")
    await upload(client, org_id, filename="mart.pdf", meta=statement_meta(
        "2026-01-01", "2026-03-31", 100_000_00, 90_000_00, identity=account_identity(first)))
    await upload(client, org_id, filename="nisan.pdf", meta=statement_meta(
        "2026-04-01", "2026-04-30", 70_000_00, 60_000_00, identity=account_identity(second)))
    async with client._maker() as db:
        return await proven_balances(db, org_id)


async def test_counterparty_ibans_in_rows_do_not_make_two_accounts(client):
    first = _file("Hesap Özeti", "02.03.2026;FAST TR33 0006 1005 1978 6457 8413 26 Ali;-100,00;900,00")
    second = _file("Hesap Özeti", f"02.04.2026;FAST {OTHER} Veli;-100,00;800,00")
    found = await _pair(client, first, second, "s1")
    assert found["opening"]["balance_cents"] == 60_000_00      # never 150,000
    assert found["opening"]["basis"] == "assumed" and len(found["questions"]) == 1


async def test_an_account_number_or_bank_name_in_a_description_does_not_either(client):
    first = _file("Hesap Özeti", "02.03.2026;Hesap No: 12345678 aidat;-100,00;900,00")
    second = _file("Hesap Özeti", "02.04.2026;Gelen havale Akbank EFT;100,00;1.000,00")
    found = await _pair(client, first, second, "s2")
    assert found["opening"]["balance_cents"] == 60_000_00 and len(found["questions"]) == 1


async def test_different_ibans_in_the_headers_are_two_accounts_and_add_up(client):
    first = _file(f"IBAN: {OWN}", "02.03.2026;Kira;-100,00;900,00")
    second = _file(f"IBAN: {OTHER}", "02.04.2026;Kira;-100,00;800,00")
    found = await _pair(client, first, second, "s3")
    assert found["opening"]["balance_cents"] == 150_000_00 and found["questions"] == []
    # The two statements end a month apart: the sum is as old as its oldest account, so only assumed (and says so).
    assert found["opening"]["basis"] == "assumed"
    assert sorted(a["identity_hint"] for a in found["accounts"]) == ["IBAN ****1326", "IBAN ****3456"]
    assert all("identity" not in a for a in found["accounts"])  # the raw number never leaves the service


async def test_a_bank_name_on_one_side_and_nothing_on_the_other_is_no_evidence_of_a_difference(client):
    first = _file("Akbank Hesap Özeti", "02.03.2026;Kira;-100,00;900,00")
    second = _file("Hesap Özeti", "02.04.2026;Kira;-100,00;800,00")
    found = await _pair(client, first, second, "s4")
    assert found["opening"]["balance_cents"] == 60_000_00 and len(found["questions"]) == 1


async def test_an_iban_against_an_account_number_is_not_a_difference_either(client):
    first = _file(f"IBAN: {OWN}", "02.03.2026;Kira;-100,00;900,00")
    second = _file("Hesap No: 12345678", "02.04.2026;Kira;-100,00;800,00")
    found = await _pair(client, first, second, "s5")
    assert found["opening"]["balance_cents"] == 60_000_00 and len(found["questions"]) == 1


async def test_one_coincident_day_does_not_join_two_accounts(client):
    """Two accounts that both stand at 10.000,00 on one shared day are not one account."""
    _, org_id, _ = await kullanici(client, "s6@example.com")
    day = {"2026-03-20": 10_000_00}
    await upload(client, org_id, filename="a.pdf", meta=statement_meta("2026-03-01", "2026-03-31", 5_000_00, 20_000_00, points=day))
    await upload(client, org_id, filename="b.pdf", meta=statement_meta("2026-03-10", "2026-04-10", 7_000_00, 30_000_00, points=day))
    async with client._maker() as db:
        found = await proven_balances(db, org_id)
    assert found["opening"]["balance_cents"] == 30_000_00 and found["opening"]["basis"] == "assumed" and len(found["questions"]) == 1


async def test_one_common_day_with_the_same_transactions_on_it_does_join(client):
    _, org_id, _ = await kullanici(client, "s7@example.com")
    day, same = {"2026-03-20": 10_000_00}, {"2026-03-20": "abc"}
    for name, end, close in (("a.pdf", "2026-03-31", 20_000_00), ("b.pdf", "2026-04-10", 30_000_00)):
        meta = statement_meta("2026-03-01", end, 5_000_00 + close, close, points=day)
        meta["balance_proof"]["day_sha"] = same
        await upload(client, org_id, filename=name, meta=meta)
    async with client._maker() as db:
        found = await proven_balances(db, org_id)
    assert found["opening"]["balance_cents"] == 30_000_00 and found["opening"]["basis"] == "known" and found["questions"] == []


def test_a_csv_with_one_or_two_balance_steps_is_assumed_like_any_other_thin_chain():
    rows = [
        {"transaction_date": "2026-03-02", "amount_cents": 10_000, "type": "expense", "balance_cents": 90_000},
        {"transaction_date": "2026-03-05", "amount_cents": 5_000, "type": "expense", "balance_cents": 85_000},
        {"transaction_date": "2026-03-09", "amount_cents": 2_000, "type": "income", "balance_cents": 87_000},
    ]
    proof = assess(rows, {"balance_check": None, "unaccounted": 0})   # a CSV: the reader gave no verdict
    assert (proof["state"], proof["basis"], proof["reason"]) == ("weak", "assumed", "yalnızca 2 bakiye adımıyla doğrulandı")
    assert assess(rows[:1], None)["basis"] is None                       # a single row never verifies
    four = [*rows, {"transaction_date": "2026-03-10", "amount_cents": 1_000, "type": "expense", "balance_cents": 86_000}]
    assert assess(four, {"balance_check": None, "unaccounted": 0})["basis"] == "known"
