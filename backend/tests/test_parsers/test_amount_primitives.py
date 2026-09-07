"""Tutar ayrıştırma — ekstre düzeninden bağımsız, gerçek Türkçe biçimlendirme.

Every bank-statement fixture in this suite was written to match the regex it
exercises, so none of them can fail. These do not depend on a layout at all:
they are the formatting rules a Turkish bank actually prints, applied to the
one primitive all seven parsers share.

Both regressions below were found this way, without a real statement.
"""
from __future__ import annotations

import pytest

from app.parsers.base import BankParser


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1.234,56", 123456),
        ("500,00", 50000),
        ("0,00", 0),
        ("3.500", 350000),              # bare dot, three digits = thousands
        ("1234.56", 123456),            # US fallback
        ("3.5", 350),                   # bare dot, not three digits = decimal
        ("₺1.500,00", 150000),
        ("1.500,00 TL", 150000),
        ("N/A", None),
        ("", None),
        ("-", None),
    ],
)
def test_turkish_amounts(raw: str, expected: int | None) -> None:
    assert BankParser.parse_turkish_amount(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1.234.567", 123456700),
        ("12.345.678", 1234567800),
        ("1.234.567,89", 123456789),
        ("123.456.789,00", 12345678900),
    ],
)
def test_amounts_over_a_million_without_kurus(raw: str, expected: int) -> None:
    """The regression: any amount over a million written without kuruş vanished.

    The thousands rule required exactly two parts, so "1.234.567" fell through
    to float(), raised ValueError, and the row was dropped without a word. A
    company with eight-figure movements simply lost them.
    """
    assert BankParser.parse_turkish_amount(raw) == expected


@pytest.mark.parametrize(
    ("raw", "negative"),
    [
        ("-4.500,00", True),
        ("−4.500,00", True),     # U+2212, what a PDF often actually contains
        ("₺-500", True),
        ("- 500,00", True),
        ("4.500,00", False),
        ("+2.000,00", False),
        ("", False),
    ],
)
def test_the_sign_is_read_from_the_text(raw: str, negative: bool) -> None:
    """`parse_turkish_amount` returns a magnitude on purpose — a
    ParsedTransaction amount is always positive and `tx_type` carries the
    direction. So the sign has to be read separately, and each of the three
    duplicated parsers also tested `amount_cents < 0`, which never fired."""
    assert BankParser.is_negative_amount(raw) is negative


def test_magnitude_is_returned_not_a_signed_number() -> None:
    assert BankParser.parse_turkish_amount("-4.500,00") == 450000


def test_a_signed_amount_still_reaches_the_right_side_of_the_ledger() -> None:
    """The two halves have to be used together, so check them together."""
    from app.parsers.banks.yapkredi import YapiKrediParser

    text = """
    YAPI VE KREDİ BANKASI
    Hesap Numarası: 12345678
    15/03/2024  MÜŞTERİ HAVALESİ   +1.250.000,00  2.000.000,00
    16/03/2024  TEDARİKÇİ ÖDEMESİ  -1.234.567     765.433,00
    """
    txs = YapiKrediParser().parse(text).transactions
    assert len(txs) == 2
    assert txs[0].tx_type == "income" and txs[0].amount_cents == 125000000
    # The row that used to disappear entirely.
    assert txs[1].tx_type == "expense" and txs[1].amount_cents == 123456700
