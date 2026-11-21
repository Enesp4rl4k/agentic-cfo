"""Which way did the money go: realistic statement layouts, each with its inflow and outflow asserted.

Before: `_kodsuz_yon` let the SIGN decide, so a bank export with ONE amount column of all-positive
numbers (direction in "B/A", "Borç/Alacak", "İşlem Tipi" or in which of two columns was filled) booked
every outflow as income. One resolver (`app.parsers.direction`) now serves every path.
"""
from __future__ import annotations

import ast
import importlib
import pkgutil
from pathlib import Path
from typing import Any

import pytest

from app.parsers.direction import (
    header_signature,
    is_non_transaction,
    norm_header,
    parse_money,
    resolve_file,
    settle_rows,
    sign_is_informative,
    statement_identity,
    value_direction,
)
from app.services.held_direction import apply_to_rows
from app.services.ingest.hold import row_reasons, split_uncertain
from app.services.ingest.rows import _try_parse_csv

NL = "\n"


def _csv(*lines: str) -> str:
    return NL.join(lines) + NL


def _read(text: str) -> list[dict[str, Any]]:
    rows = _try_parse_csv(text)
    assert rows, "the statement was not read at all"
    return rows


def totals(rows: list[dict[str, Any]]) -> tuple[int, int, int]:
    """(inflow, outflow, rows waiting) in kuruş."""
    inflow = sum(r["amount_cents"] for r in rows if r["type"] == "income")
    outflow = sum(r["amount_cents"] for r in rows if r["type"] == "expense")
    return inflow, outflow, sum(1 for r in rows if r["type"] not in ("income", "expense"))


# ── the layouts ──────────────────────────────────────────────────────────────

SIGNED_SINGLE = _csv(
    "Tarih;Açıklama;Tutar",
    "01.03.2026;Müşteri tahsilatı;5.000,00",
    "02.03.2026;Kira;-1.250,50",
    "03.03.2026;Satış;2.000,00",
    "04.03.2026;Elektrik;(300,00)",
)
SIGNED_SINGLE_BALANCE = _csv(
    "Tarih;Açıklama;Tutar;Bakiye",
    "01.03.2026;Müşteri tahsilatı;5.000,00;15.000,00",
    "02.03.2026;Kira;-1.250,50;13.749,50",
    "03.03.2026;Satış;2.000,00;15.749,50",
    "04.03.2026;Elektrik;(300,00);15.449,50",
)
POSITIVE_WITH_BA = _csv(
    "Tarih;Açıklama;Tutar;B/A",
    "01.03.2026;Müşteri tahsilatı;1.000,00;A",
    "02.03.2026;Kira;400,00;B",
    "03.03.2026;Elektrik;250,00;B",
    "04.03.2026;Satış;3.000,00;A",
)
POSITIVE_WITH_BORC_ALACAK_WORDS_AND_BALANCE = _csv(
    "Tarih;Açıklama;Tutar;Borç/Alacak;Bakiye",
    "01.03.2026;Satış;1.000,00;Alacak;11.000,00",
    "02.03.2026;Kira;400,00;Borç;10.600,00",
    "03.03.2026;Elektrik;250,00;Borç;10.350,00",
    "04.03.2026;Satış;3.000,00;Alacak;13.350,00",
)
ISLEM_TIPI = _csv(
    "Tarih;Açıklama;İşlem Tipi;Tutar",
    "01.03.2026;Maaş;Giden Havale;12.000,00",
    "02.03.2026;Satış;Gelen Havale;30.000,00",
)
SPLIT_BLANKS = _csv(
    "Tarih;Açıklama;Borç;Alacak",
    "01.03.2026;Kira;1.500,00;",
    "02.03.2026;Satış;;4.000,00",
    "03.03.2026;Elektrik;250,50;",
)
SPLIT_ZEROS = _csv(
    "Tarih;Açıklama;Borç Tutarı;Alacak Tutarı",
    "01.03.2026;Kira;1.500,00;0,00",
    "02.03.2026;Satış;0,00;4.000,00",
    "03.03.2026;Elektrik;250,50;0,00",
)
SPLIT_WITH_BALANCE = _csv(
    "Tarih;Açıklama;Borç;Alacak;Bakiye",
    "01.03.2026;Kira;1.500,00;;8.500,00",
    "02.03.2026;Satış;;4.000,00;12.500,00",
    "03.03.2026;Elektrik;250,50;;12.249,50",
)
ENGLISH_SPLIT = _csv(
    "Date;Description;Withdrawal;Deposit",
    "01.03.2026;Rent;1500.00;",
    "02.03.2026;Sales;;4000.00",
)
PAYMENT_COLLECTION = _csv(
    "Tarih;Açıklama;Ödeme;Tahsilat",
    "01.03.2026;Kira;1.500,00;",
    "02.03.2026;Satış;;4.000,00",
)
ALL_NEGATIVE = _csv(
    "Tarih;Açıklama;Tutar",
    "01.03.2026;Kira;-100,00",
    "02.03.2026;Elektrik;-200,50",
    "03.03.2026;Su;-50,00",
)
# The bank's view: its "Borç" column is what it owes the customer, so a "Borç" row RAISES the
# balance. Read with the customer's mapping the balance contradicts every row.
BANK_PERSPECTIVE = _csv(
    "Tarih;Açıklama;Borç;Alacak;Bakiye",
    "01.03.2026;Satış;3.000,00;;13.000,00",
    "02.03.2026;Kira;;1.200,00;11.800,00",
    "03.03.2026;Satış;2.000,00;;13.800,00",
    "04.03.2026;Elektrik;;300,00;13.500,00",
)
NO_SIGNAL = _csv(
    "Tarih;Açıklama;Tutar",
    "01.03.2026;Bir;100,00",
    "02.03.2026;İki;200,00",
)

CASES = [
    # layout, inflow, outflow, waiting: booked with no question
    ("signed single column", SIGNED_SINGLE, 700000, 155050, 0),
    ("signed single column with balance", SIGNED_SINGLE_BALANCE, 700000, 155050, 0),
    ("all-positive, Borç/Alacak words, balance agrees", POSITIVE_WITH_BORC_ALACAK_WORDS_AND_BALANCE, 400000, 65000, 0),
    ("İşlem Tipi column (Ödeme/Tahsilat)", ISLEM_TIPI, 3000000, 1200000, 0),
    ("separate columns with balance, agrees", SPLIT_WITH_BALANCE, 400000, 175050, 0),
    ("English Withdrawal/Deposit", ENGLISH_SPLIT, 400000, 150000, 0),
    ("Ödeme/Tahsilat", PAYMENT_COLLECTION, 400000, 150000, 0),
]

# Debit/credit words with no balance to verify them: whose book is "Borç"? Held with ONE question; the totals
# are what each answer gives: (layout, as the columns say: in, out; inverted: in, out)
CONVENTION_CASES = [
    ("all-positive amounts, B/A column", POSITIVE_WITH_BA, (400000, 65000), (65000, 400000)),
    ("separate Borç/Alacak with blanks", SPLIT_BLANKS, (400000, 175050), (175050, 400000)),
    ("separate columns with 0,00", SPLIT_ZEROS, (400000, 175050), (175050, 400000)),
]


@pytest.mark.parametrize(("name", "text", "inflow", "outflow", "waiting"), CASES, ids=[c[0] for c in CASES])
def test_layout_totals(name: str, text: str, inflow: int, outflow: int, waiting: int) -> None:
    rows = _read(text)
    assert totals(rows) == (inflow, outflow, waiting), name
    assert all("direction_file" not in r for r in rows)


@pytest.mark.parametrize(("name", "text", "as_read", "inverted"), CONVENTION_CASES, ids=[c[0] for c in CONVENTION_CASES])
def test_a_debit_credit_reading_nothing_can_verify_is_asked_not_booked(name, text, as_read, inverted) -> None:
    rows = _read(text)
    assert totals(rows)[:2] == (0, 0) and all(r["type"] is None for r in rows), name   # nothing in a total
    assert {r["direction_file"]["reason"] for r in rows} == {"convention_unverified"}
    q = next(r["direction_question"] for r in rows if "direction_question" in r)
    assert q["mapping"] and {m["means"] for m in q["mapping"]} == {"expense", "income"}
    assert all(s.get("description") for s in q["samples"])                              # the person sees descriptions
    assert [r["direction_file"]["identity"] for r in rows] == [False] * len(rows)
    for answer, expected in (("as_read", as_read), ("inverted", inverted)):
        copy = [{**r, "direction_file": dict(r["direction_file"])} for r in rows]
        apply_to_rows(copy, answer)
        assert totals(copy) == (*expected, 0), (name, answer)


def test_the_bank_view_without_a_balance_is_asked_and_the_inverted_answer_books_it_right() -> None:
    bank_view = _csv(
        "Tarih;Açıklama;Borç;Alacak",
        "01.03.2026;Satış;3.000,00;",       # the bank's "Borç": it owes the customer, money came in
        "02.03.2026;Kira;;1.200,00",
        "03.03.2026;Satış;2.000,00;",
    )
    rows = _read(bank_view)
    assert totals(rows) == (0, 0, 3)                       # not booked as the customer's view
    apply_to_rows(rows, "inverted")
    assert totals(rows) == (500000, 120000, 0)


def test_all_negative_without_a_balance_is_a_guess_and_is_held() -> None:
    rows = _read(ALL_NEGATIVE)
    assert totals(rows) == (0, 0, 3) and {r["direction_file"]["reason"] for r in rows} == {"no_signal"}


def test_a_stray_reversal_does_not_make_every_other_row_income() -> None:
    rows = _read(_csv("Tarih;Açıklama;Tutar", *[f"{d:02d}.03.2026;Satış {d};100,00" for d in range(1, 10)],
                      "10.03.2026;İade;-100,00"))
    assert totals(rows) == (0, 0, 10) and {r["direction_file"]["reason"] for r in rows} == {"sign_unconfirmed"}
    assert sign_is_informative([False] * 9 + [True]) is False        # one reversal: asked, not assumed
    assert sign_is_informative([False, True, False, True]) is True    # genuinely mixed
    assert sign_is_informative([True] * 37 + [False] * 3) is True     # an ordinary month: 37 out, 3 in
    assert sign_is_informative([True, True, True]) is False and sign_is_informative([False] * 3) is False


def test_a_balance_can_make_a_rare_sign_informative() -> None:
    lines = ["Tarih;Açıklama;Tutar;Bakiye"]
    balance = 1000
    for d in range(1, 10):
        balance += 100
        lines.append(f"{d:02d}.03.2026;Satış {d};100,00;{balance},00")
    balance -= 50
    lines.append(f"10.03.2026;İade;-50,00;{balance},00")
    rows = _read(_csv(*lines))
    assert totals(rows) == (90000, 5000, 0)


def test_rows_that_do_not_reconcile_with_the_balance_are_held_one_by_one() -> None:
    lines, balance = ["Tarih;Açıklama;Tutar;Bakiye"], 10000
    for d in range(1, 13):
        amount = 100 if d % 2 else -50
        balance += amount
        shown = amount
        if d == 7:
            shown = 70                      # the statement says 70, the balance moved 100: a row is wrong or missing
        lines.append(f"{d:02d}.03.2026;Hareket {d};{shown},00;{balance},00")
    rows = _read(_csv(*lines))
    held = [r for r in rows if r["type"] is None]
    assert [r["description"] for r in held] == ["Hareket 7"] and held[0]["balance_mismatch"] is True
    assert row_reasons({**held[0], "currency": "TRY"}) == ["balance_mismatch"]
    assert len(rows) - len(held) == 11                 # the rest of a verified statement is booked


def test_a_verified_statement_leaves_no_row_held_and_the_first_row_is_not_asked() -> None:
    for text in (SIGNED_SINGLE_BALANCE, SPLIT_WITH_BALANCE, POSITIVE_WITH_BORC_ALACAK_WORDS_AND_BALANCE):
        assert [r for r in _read(text) if r["type"] is None] == []


def test_a_balance_that_reconciles_only_part_of_the_rows_holds_the_file_with_the_rate() -> None:
    rows = _read(_csv(
        "Tarih;Açıklama;Tutar;Bakiye",
        "01.03.2026;Satış;1.000,00;11.000,00",
        "02.03.2026;Kira;-400,00;10.600,00",
        "03.03.2026;Bir;-250,00;5.000,00",
        "04.03.2026;İki;500,00;1.000,00",
    ))
    assert {r["direction_file"]["reason"] for r in rows} == {"balance_inconclusive"}
    q = next(r["direction_question"] for r in rows if "direction_question" in r)
    assert "%33" in q["note"]


def test_carried_balance_and_total_lines_are_skipped_and_anchor_the_chain() -> None:
    rows = _read(_csv(
        "Tarih;Açıklama;Tutar;Bakiye",
        "01.03.2026;Devreden Bakiye;;10.000,00",
        "02.03.2026;Kira;400,00;9.600,00",
        "03.03.2026;Satış;1.000,00;10.600,00",
        "04.03.2026;Elektrik;250,00;10.350,00",
        "05.03.2026;Toplam;;10.350,00",
    ))
    assert [r["description"] for r in rows] == ["Kira", "Satış", "Elektrik"]       # no row held for a total line
    assert [r["type"] for r in rows] == ["expense", "income", "expense"]            # the opening balance read the first row
    assert is_non_transaction("Devreden Bakiye") and is_non_transaction("Genel Toplam") and not is_non_transaction("Toplu ödeme")


def test_an_amount_column_beside_debit_credit_columns_must_agree() -> None:
    rows = _read(_csv(
        "Tarih;Açıklama;Tutar;Ödeme;Tahsilat",
        "01.03.2026;Kira;1.500,00;1.500,00;",
        "02.03.2026;Satış;4.000,00;;4.000,00",
        "03.03.2026;Tutmayan;999,00;1.500,00;",       # the two sources disagree: held
        "04.03.2026;Ters;-300,00;;300,00",            # a negative "Tutar" on a credit: disagree
    ))
    assert [r["type"] for r in rows] == ["expense", "income", None, None]


def test_the_identity_of_a_statement_is_in_its_signature() -> None:
    assert statement_identity("Akbank A.Ş. Hesap No: 1234567 IBAN TR33 0006 1005 1978 6457 8413 26").startswith("iban:TR33")
    assert statement_identity("Hesap No: 1234-567").startswith("acct:1234567")
    assert statement_identity("AKBANK T.A.Ş. HESAP HAREKETLERİ") == "bank:akbank"
    assert statement_identity("Tarih Tutar") == ""
    h = ["Tarih", "Tutar"]
    assert header_signature(h, "iban:A") != header_signature(h, "iban:B") != header_signature(h)


def test_an_all_positive_column_with_no_other_signal_is_never_income() -> None:
    rows = _read(NO_SIGNAL)
    assert [r["type"] for r in rows] == [None, None]
    assert {r["direction_file"]["reason"] for r in rows} == {"no_signal"}
    assert len({r["direction_file"]["key"] for r in rows}) == 1          # one file, one question
    assert sum("direction_question" in r for r in rows) == 1
    accepted, held = split_uncertain([{**r, "currency": "TRY"} for r in rows])
    assert not accepted and all(h["hold_reasons"] == ["direction_file_unknown"] for h in held)


def test_the_question_shows_the_columns_and_sample_rows() -> None:
    q = next(r["direction_question"] for r in _read(NO_SIGNAL) if "direction_question" in r)
    assert [c["role"] for c in q["columns"]] == ["date", "description", "amount"]
    assert q["samples"][0] == {"date": "01.03.2026", "description": "Bir", "amount": "100,00"}
    assert len(q["samples"]) == 2


def test_bank_perspective_is_caught_by_the_balance_and_the_whole_file_waits() -> None:
    rows = _read(BANK_PERSPECTIVE)
    assert totals(rows) == (0, 0, 4)                                  # nothing booked backwards
    assert {r["direction_file"]["reason"] for r in rows} == {"balance_contradicts"}
    # what the columns said and what the balance says are kept for the one question
    assert [r["direction_file"]["read"] for r in rows] == ["expense", "income", "expense", "income"]
    assert [r["direction_file"]["balance"] for r in rows] == ["income", "expense", "income", "expense"]
    # the person answers "the balance is right": 5.000,00 in, 1.500,00 out
    apply_to_rows(rows, "balance")
    assert totals(rows) == (500000, 150000, 0)
    assert all("direction_file" not in r and not row_reasons({**r, "currency": "TRY"}) for r in rows)
    assert [r["category"] is not None for r in rows] == [True] * 4        # chosen once the direction is known


def test_answering_as_read_keeps_the_columns_reading() -> None:
    rows = _read(BANK_PERSPECTIVE)
    apply_to_rows(rows, "as_read")
    assert totals(rows) == (150000, 500000, 0)


def test_newest_first_statements_verify_too() -> None:
    newest_first = _csv(
        "Tarih;Açıklama;Tutar;Bakiye",
        "04.03.2026;Elektrik;-300,00;15.449,50",
        "03.03.2026;Satış;2.000,00;15.749,50",
        "02.03.2026;Kira;-1.250,50;13.749,50",
        "01.03.2026;Satış;5.000,00;15.000,00",
    )
    assert totals(_read(newest_first)) == (700000, 155050, 0)


def test_balance_alone_can_read_a_statement_that_says_nothing_else() -> None:
    rows = _read(_csv(
        "Tarih;Açıklama;Tutar;Bakiye",
        "01.03.2026;Açılış;100,00;1.000,00",
        "02.03.2026;Kira;400,00;600,00",
        "03.03.2026;Satış;1.000,00;1.600,00",
        "04.03.2026;Elektrik;250,00;1.350,00",
    ))
    # the first row has no balance before it: it waits on its own, the rest are read from the arithmetic
    assert [r["type"] for r in rows] == [None, "expense", "income", "expense"]
    assert all("direction_file" not in r for r in rows)
    assert row_reasons({**rows[0], "currency": "TRY"}) == ["direction_unknown"]


def test_both_columns_filled_holds_that_row_only() -> None:
    rows = _read(_csv(
        "Tarih;Açıklama;Ödeme;Tahsilat",
        "01.03.2026;Kira;100,00;",
        "02.03.2026;Karışık;50,00;70,00",
        "03.03.2026;Satış;;300,00",
    ))
    assert [r["type"] for r in rows] == ["expense", None, "income"]
    assert rows[1]["amount_cents"] is None and "direction_file" not in rows[1]


def test_an_unknown_direction_value_holds_that_row() -> None:
    rows = _read(_csv(
        "Tarih;Açıklama;Tutar;İşlem Tipi",
        "01.03.2026;Kira;100,00;Çıkış",
        "02.03.2026;Garip;50,00;X",
        "03.03.2026;Satış;300,00;Giriş",
    ))
    assert [r["type"] for r in rows] == ["expense", None, "income"]


def test_a_type_column_that_is_not_a_direction_is_not_read_as_one() -> None:
    rows = _read(_csv(
        "Tarih;Açıklama;İşlem Tipi;Tutar",
        "01.03.2026;Kira;EFT;-100,00",
        "02.03.2026;Satış;HAVALE;300,00",
    ))
    assert [r["type"] for r in rows] == ["expense", "income"]          # the sign, which varies in this file


def test_the_explicit_income_expense_values_are_still_honoured() -> None:
    rows = _read(_csv(
        "tarih;açıklama;tutar;tip;kategori",
        "03.01.2024;Lisans;285.000,00;income;sales",
        "05.01.2024;Kira;-28.500,00;expense;rent",
    ))
    assert totals(rows) == (28500000, 2850000, 0)


def test_an_unreadable_amount_is_held_not_booked_as_zero() -> None:
    rows = _read(_csv("Tarih;Açıklama;Tutar", "01.03.2026;Kira;-100,00", "02.03.2026;Bozuk;abc", "03.03.2026;Satış;50,00"))
    assert rows[1]["amount_cents"] is None
    assert "amount_unreadable" in row_reasons({**rows[1], "currency": "TRY"})


def test_a_row_with_a_known_account_still_follows_its_account() -> None:
    rows = _read(_csv(
        "Tarih;Hesap Kodu;Açıklama;Borç;Alacak",
        "01.03.2026;770.01;Genel gider;500,00;",
        "02.03.2026;600.01;Satış;;900,00",
    ))
    assert totals(rows)[:2] == (90000, 50000)


# ── the other upload paths use the same resolver ─────────────────────────────

def _pdf_rows(*items: tuple[str | None, int, int | None]) -> list[dict[str, Any]]:
    return [{"type": t, "amount_cents": a, "balance_cents": b, "description": f"r{i}"} for i, (t, a, b) in enumerate(items)]


def test_text_parsed_statements_are_checked_against_their_balance_too() -> None:
    rows = _pdf_rows(("expense", 100, 900), ("expense", 200, 1100), ("expense", 50, 1150),
                     ("expense", 10, 1160), ("expense", 40, 1200))
    # every balance went UP by the amount the parser read as money out: it read the file backwards
    hold = settle_rows(rows, "Garanti")
    assert hold is not None and hold["reason"] == "balance_contradicts"
    assert [r["type"] for r in rows] == [None] * 5
    assert [r["direction_balance"] for r in rows] == ["income"] * 5


def test_a_text_statement_that_agrees_with_its_balance_is_untouched() -> None:
    rows = _pdf_rows(("expense", 100, 900), ("income", 200, 1100), ("expense", 50, 1050))
    assert settle_rows(rows, "Garanti") is None and [r["type"] for r in rows] == ["expense", "income", "expense"]


def test_a_text_statement_where_the_parser_placed_nothing_is_held_or_read_from_the_balance() -> None:
    held = _pdf_rows((None, 100, None), (None, 200, None))
    assert (settle_rows(held, "Akbank") or {}).get("reason") == "no_signal"
    derived = _pdf_rows((None, 100, 900), (None, 200, 1100), (None, 50, 1050))
    assert settle_rows(derived, "Akbank") is None
    assert [r["type"] for r in derived] == [None, "income", "expense"]


def test_a_text_layout_with_all_positive_amounts_does_not_default_to_income() -> None:
    from app.parsers.banks.garanti import GarantiParser

    positive = "GARANTİ BBVA" + NL + "10.02.2024  FATURA  2.000,00  12.000,00" + NL + "12.02.2024  MAAŞ  4.500,00  7.500,00" + NL
    statement = GarantiParser().parse(positive)
    assert [t.tx_type for t in statement.transactions] == ["", ""]
    assert [t.balance_cents for t in statement.transactions] == [1200000, 750000]


# ── numbers ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(("raw", "expected"), [
    ("1.234,56", (123456, False)), ("-1.234,56", (123456, True)), ("1.234,56-", (123456, True)),
    ("(1.234,56)", (123456, True)), ("1.234,56 TL", (123456, False)), ("₺1.234,56", (123456, False)),
    ("-1.234,56 TRY", (123456, True)), ("1,234.56", (123456, False)), ("1234.56", (123456, False)),
    ("1.234", (123400, False)), ("1.234.567", (123456700, False)), ("12,5", (1250, False)),
    ("0,00", (0, False)), ("500,00 TL-", (50000, True)), ("€ 99,90", (9990, False)),
    ("−75,00", (7500, True)), ("", None), ("abc", None), (None, None),
])
def test_turkish_number_formats(raw: Any, expected: Any) -> None:
    assert parse_money(raw) == expected


def test_header_aliases() -> None:
    assert norm_header("Borç Tutarı (TL)") == "borc tutari" and norm_header("B/A") == "b a"
    assert norm_header("İşlem Tipi") == "islem tipi"
    assert header_signature(["Tarih", "Tutar"]) == header_signature(["TARİH", "tutar"])
    assert header_signature(["Tarih", "Tutar"]) != header_signature(["Tutar", "Tarih"])
    for word, direction in (("B", "expense"), ("Borç", "expense"), ("Çıkış", "expense"),
                            ("Debit", "expense"), ("A", "income"), ("Alacak", "income"), ("Giriş", "income"),
                            ("Tahsilat", "income"), ("Credit", "income"), ("EFT", None), ("", None),
                            ("Gelen Ödeme", "income"), ("Giden Ödeme", "expense"), ("Gelen Havale", "income"),
                            ("Giden EFT", "expense"), ("Para Yatırma", "income"), ("Para Çekme", "expense"),
                            ("Ödeme", None), ("Havale", None), ("FAST", None), ("Virman", None)):
        assert value_direction(word) == direction, word


def test_resolver_is_pure_and_never_returns_a_default() -> None:
    out = resolve_file(["tarih", "tutar"], [{"tarih": "01.03.2026", "tutar": "10,00"}])
    assert out.hold is not None and out.rows[0].type is None


# ── an Excel statement: the real path for spreadsheets ───────────────────────

def test_an_excel_statement_with_odeme_tahsilat_columns_is_read_by_those_columns(tmp_path: Path) -> None:
    from openpyxl import Workbook

    from app.services.ingest.rows import _tablo_ekstresi

    wb = Workbook()
    ws = wb.active
    ws.append(["Örnek Banka A.Ş. Hesap Hareketleri"])
    ws.append([])
    ws.append(["İşlem Tarihi", "Açıklama", "Ödeme", "Tahsilat", "Bakiye"])
    ws.append(["01.03.2026", "Kira", "1.500,00", None, "8.500,00"])
    ws.append(["02.03.2026", "Satış", None, "4.000,00", "12.500,00"])
    ws.append(["03.03.2026", "Elektrik", "250,50", None, "12.249,50"])
    path = tmp_path / "ekstre.xlsx"
    wb.save(path)
    assert totals(_tablo_ekstresi(str(path)) or []) == (400000, 175050, 0)


def test_an_excel_statement_of_all_positive_amounts_waits_as_one_file(tmp_path: Path) -> None:
    from openpyxl import Workbook

    from app.services.ingest.rows import _tablo_ekstresi

    wb = Workbook()
    ws = wb.active
    ws.append(["Tarih", "Açıklama", "Tutar"])
    ws.append(["01.03.2026", "Bir", 100])
    ws.append(["02.03.2026", "İki", 200])
    path = tmp_path / "ekstre.xlsx"
    wb.save(path)
    rows = _tablo_ekstresi(str(path)) or []
    assert [r["type"] for r in rows] == [None, None] and len({r["direction_file"]["key"] for r in rows}) == 1


# ── architecture: one implementation, and nothing unreachable ────────────────

def test_every_parser_class_is_reachable_from_the_upload_entry_point() -> None:
    """`GenericParser` was reached only through `ParserRegistry.parse`, which nothing called, so its
    direction logic never ran. A parser must be registered (reached by `ParserRegistry.detect`, which the
    upload entry point calls) or it is dead code."""
    import app.parsers as parsers_pkg
    from app.parsers import registry
    from app.parsers.base import BankParser

    for mod in pkgutil.walk_packages(parsers_pkg.__path__, "app.parsers."):
        importlib.import_module(mod.name)
    registry._ensure_parsers_registered()

    def concrete(cls: type) -> set[type]:
        found: set[type] = set()
        for sub in cls.__subclasses__():
            found |= concrete(sub) | ({sub} if not getattr(sub, "__abstractmethods__", None) else set())
        return found

    registered = set(registry._REGISTRY)
    unreachable = {c.__name__ for c in concrete(BankParser) if c not in registered and c.bank_id and c.__module__.startswith("app.parsers")}
    assert not unreachable, f"parser classes not reachable from the upload entry point: {sorted(unreachable)}"

    entry = Path(__file__).resolve().parents[1] / "app" / "agents" / "data_ingestion.py"
    calls = {n.attr for n in ast.walk(ast.parse(entry.read_text(encoding="utf-8"))) if isinstance(n, ast.Attribute)}
    assert "detect" in calls, "the upload entry point no longer reaches ParserRegistry.detect"
    assert not hasattr(registry.ParserRegistry, "parse"), "a second entry (ParserRegistry.parse) that nothing calls"


def test_one_direction_implementation_exists() -> None:
    """No module besides app.parsers.direction decides a statement row's direction from a sign column."""
    root = Path(__file__).resolve().parents[1] / "app"
    offenders = [
        str(p.relative_to(root)) for p in root.rglob("*.py")
        if "_kodsuz_yon" in p.read_text(encoding="utf-8") or "def _parse_csv_transactions" in p.read_text(encoding="utf-8")
    ]
    assert not offenders, offenders


# ── round 3: nothing is dropped unseen, skew is not punished, vocabulary is kept ─────────────────────────────

def test_real_rows_that_merely_begin_like_a_summary_line_are_booked() -> None:
    rows = _read(_csv(
        "Tarih;Açıklama;Tutar",
        "01.03.2026;Toplam fatura ödemesi;-1.500,00",
        "02.03.2026;Devreden KDV;-300,00",
        "03.03.2026;Total Wireless;-80,00",
        "04.03.2026;Satış;5.000,00",
    ))
    assert [r["description"] for r in rows] == ["Toplam fatura ödemesi", "Devreden KDV", "Total Wireless", "Satış"]
    assert totals(rows) == (500000, 188000, 0) and not any("summary_lines_skipped" in r for r in rows)


def test_exact_summary_lines_are_skipped_and_counted() -> None:
    rows = _read(_csv(
        "Tarih;Açıklama;Tutar;Bakiye",
        ";Devreden Bakiye;;10.000,00",
        "02.03.2026;Kira;-400,00;9.600,00",
        "03.03.2026;Satış;1.000,00;10.600,00",
        "04.03.2026;Elektrik;-250,00;10.350,00",
        ";Genel Toplam;;10.350,00",
    ))
    assert [r["description"] for r in rows] == ["Kira", "Satış", "Elektrik"]
    assert rows[0]["summary_lines_skipped"] == 2                  # reported, not silent
    from app.services.ingest.summary import ingest_summary

    assert "2 özet satırı atlandı" in ingest_summary(rows, {}, 2)["summary"]


def test_a_summary_phrase_with_a_date_and_an_amount_is_held_when_it_does_not_fit() -> None:
    lines, balance = ["Tarih;Açıklama;Tutar;Bakiye"], 10000
    for d in range(1, 11):
        amount = 100 if d % 2 else -50
        balance += amount
        lines.append(f"{d:02d}.03.2026;Hareket {d};{amount},00;{balance},00")
    lines.append("11.03.2026;Toplam;777,00;99.999,00")      # a date and an amount that does not fit the chain
    rows = _read(_csv(*lines))
    held = [r for r in rows if r.get("summary_suspect")]
    assert [r["description"] for r in held] == ["Toplam"]
    assert row_reasons({**held[0], "currency": "TRY"}) == ["summary_suspect"]
    assert len(rows) == 11                                   # not skipped, not booked: held


def test_a_collections_light_month_is_booked_without_a_question() -> None:
    lines = ["Tarih;Açıklama;Tutar"] + [f"{d:02d}.03.2026;Ödeme {d};-{d * 10},00" for d in range(1, 11)]
    lines += ["11.03.2026;Tahsilat;500,00", "12.03.2026;Tahsilat;300,00", "13.03.2026;Tahsilat;200,00"]
    rows = _read(_csv(*lines))
    assert totals(rows) == (100000, 55000, 0) and not any("direction_file" in r for r in rows)


def test_two_stray_positives_among_payments_ask_once_and_the_sign_answer_books_it() -> None:
    lines = ["Tarih;Açıklama;Tutar"] + [f"{d:02d}.03.2026;Ödeme {d};-{d},00" for d in range(1, 21)]
    lines += ["21.03.2026;Tahsilat;50,00", "22.03.2026;Tahsilat;70,00"]
    rows = _read(_csv(*lines))
    assert {r["direction_file"]["reason"] for r in rows} == {"sign_unconfirmed"} and totals(rows)[:2] == (0, 0)
    q = next(r["direction_question"] for r in rows if "direction_question" in r)
    assert {m["means"] for m in q["mapping"]} == {"expense", "income"}
    apply_to_rows(rows, "sign_correct")
    assert totals(rows) == (12000, 21000, 0)


def test_unambiguous_words_book_after_normalisation_and_the_question_quotes_the_files_own_columns(tmp_path) -> None:
    from openpyxl import Workbook

    from app.services.ingest.rows import _tablo_ekstresi

    def sheet(name: str, debit: str, credit: str):
        wb = Workbook()
        ws = wb.active
        ws.append(["Tarih", "Açıklama", debit, credit])
        ws.append(["01.03.2026", "Kira", "1.500,00", None])
        ws.append(["02.03.2026", "Satış", None, "4.000,00"])
        path = tmp_path / name
        wb.save(path)
        return _tablo_ekstresi(str(path)) or []

    assert totals(sheet("cikis.xlsx", "Çıkış", "Giriş")) == (400000, 150000, 0)
    assert totals(sheet("giden.xlsx", "Giden Tutar", "Gelen Tutar")) == (400000, 150000, 0)
    asked = sheet("borc.xlsx", "Borç Tutarı", "Alacak Tutarı")
    q = next(r["direction_question"] for r in asked if "direction_question" in r)
    assert [m["label"] for m in q["mapping"]] == ["Borç Tutarı", "Alacak Tutarı"]
    assert [c["name"] for c in q["columns"]][2:] == ["Borç Tutarı", "Alacak Tutarı"]


def test_a_bare_payment_type_value_is_not_a_direction() -> None:
    rows = _read(_csv(
        "Tarih;Açıklama;İşlem Tipi;Tutar",
        "01.03.2026;Kira;Ödeme;-100,00",
        "02.03.2026;Satış;Havale;300,00",
        "03.03.2026;Gaz;EFT;-50,00",
    ))
    assert [r["type"] for r in rows] == ["expense", "income", "expense"]            # by the sign, since the column is no direction
    assert all("direction_file" not in r for r in rows)


def test_a_two_row_text_statement_is_unverified_and_a_debit_credit_layout_asks() -> None:
    two = _pdf_rows(("expense", 100, 900), ("income", 200, 1100))
    assert settle_rows(two, "Ziraat", ambiguous=False) is None and [r["type"] for r in two] == ["expense", "income"]
    asked = settle_rows(_pdf_rows(("expense", 100, 900), ("income", 200, 1100)), "Ziraat", ambiguous=True)
    assert asked is not None and asked["reason"] == "convention_unverified"
    five = _pdf_rows(("expense", 100, 900), ("income", 200, 1100), ("expense", 50, 1050),
                     ("income", 10, 1060), ("expense", 60, 1000))
    assert settle_rows(five, "Ziraat", ambiguous=True) is None                       # enough steps, all reconcile
