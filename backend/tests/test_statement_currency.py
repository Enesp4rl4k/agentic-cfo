"""A currency is stated only if the document says so; otherwise the row goes the held-row way.

Review of PR #110, item 2: a USD account's statement was booked as TRY because the bank parsers, the
accounting parsers and the e-belge converters wrote "TRY" for an unstated currency, and `_detect_currency`
found TRY inside words such as "ENTRY" and "COUNTRY".
"""
from __future__ import annotations

import pytest

from app.parsers.banks.garanti import GarantiParser
from app.parsers.banks.yapkredi import YapiKrediParser
from app.parsers.base import ParsedTransaction
from app.services.ingest.cells import _detect_currency
from app.services.ingest.ebelge import _try_parse_ubl_xml
from app.services.ingest.hold import resolve_currency, split_uncertain
from app.services.ingest.rows import _statement_to_transactions
from tests.test_efatura_integration import SAMPLE_UBL_TR_XML

NL = "\n"


@pytest.mark.parametrize(("text", "expected"), [
    ("ENTRY LIST OF COUNTRY CODES", None),               # TRY inside a word says nothing
    ("RETRY AFTER 5 MINUTES", None),
    ("GOLDEN DOLLARS AND EUROPE", None),                  # nor does EUR inside EUROPE
    ("Bakiye TL", "TRY"), ("Tutar (₺)", "TRY"), ("TRY", "TRY"), ("amounts in TL.", "TRY"),
    ("Hesap Para Birimi: USD" + NL + "Bakiye TL", "USD"),  # the account's own field wins over a stray symbol
    ("Döviz Cinsi : EUR", "EUR"), ("Currency: GBP", "GBP"), ("Tutar €", "EUR"), ("Amount $ 5", "USD"),
    ("USD ALIŞ 5 TL", None),                              # two currencies mentioned: it has not said which
    ("tarih,tutar", None),
])
def test_detect_currency_uses_tokens_and_the_account_field(text: str, expected: str | None) -> None:
    assert _detect_currency(text) == expected


def test_a_statement_that_states_no_currency_is_not_try() -> None:
    text = "YAPI KREDİ" + NL + "01.03.2026  Kira  -1.000,00  9.000,00" + NL + "02.03.2026  Satış  500,00  9.500,00" + NL
    statement = YapiKrediParser().parse(text)
    assert [t.currency for t in statement.transactions] == ["", ""]
    rows = _statement_to_transactions(statement)
    assert [r["currency"] for r in rows] == [None, None]
    resolve_currency(rows, text, None)
    accepted, held = split_uncertain(rows)
    assert not accepted and all("currency_unknown" in h["hold_reasons"] for h in held)


def test_a_foreign_account_statement_takes_the_currency_its_header_states() -> None:
    text = ("GARANTİ BBVA" + NL + "Hesap Para Birimi: USD" + NL
            + "10.02.2024  15.02.2024  FATURA  +2.000,00  12.000,00" + NL
            + "12.02.2024  12.02.2024  MAAŞ  -4.500,00  7.500,00" + NL)
    rows = _statement_to_transactions(GarantiParser().parse(text))
    resolve_currency(rows, text, "TRY")                     # even with a confirmed lira base
    assert {r["currency"] for r in rows} == {"USD"} and not any(r.get("currency_assumed") for r in rows)


def test_without_a_stated_currency_the_confirmed_base_is_used_and_marked_assumed() -> None:
    rows = _statement_to_transactions(GarantiParser().parse(
        "GARANTİ BBVA" + NL + "10.02.2024  FATURA  +2.000,00  12.000,00" + NL + "12.02.2024  MAAŞ  -4.500,00  7.500,00" + NL))
    resolve_currency(rows, "GARANTİ BBVA", "EUR")
    assert {(r["currency"], r["currency_assumed"]) for r in rows} == {("EUR", True)}


def test_the_parsed_transaction_has_no_default_currency() -> None:
    from datetime import UTC, datetime

    assert ParsedTransaction(date=datetime.now(UTC), description="x", amount_cents=1, tx_type="income").currency == ""


def test_an_invoice_without_a_document_currency_code_is_held_not_read_as_lira() -> None:
    no_code = SAMPLE_UBL_TR_XML.replace("<cbc:DocumentCurrencyCode>TRY</cbc:DocumentCurrencyCode>", "")
    rows = _try_parse_ubl_xml(no_code, "1234567890") or []
    assert rows and all(r["currency"] is None for r in rows)
    accepted, held = split_uncertain(rows)
    assert not accepted and "currency_unknown" in held[0]["hold_reasons"]
    stated = _try_parse_ubl_xml(SAMPLE_UBL_TR_XML, "1234567890") or []
    assert {r["currency"] for r in stated} == {"TRY"}


def test_no_hard_coded_try_is_left_on_the_upload_path() -> None:
    """The statutory e-Defter (app/parsers/edefter) may keep TRY: it is kept in lira by law, and says why.
    Nothing else on the path may default an unstated currency to it."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "app"
    pattern = re.compile(r"""(currency\w*\s*[:=]\s*["']TRY["']|or\s+["']TRY["']|["']cbc:DocumentCurrencyCode["'],\s*["']TRY["'])""")
    offenders = [
        f"{path.relative_to(root)}:{n}"
        for rel in ("parsers/banks", "parsers/accounting", "parsers/invoice", "services/ingest")
        for path in (root / rel).rglob("*.py")
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if pattern.search(line.split("#", 1)[0])
    ]
    assert not offenders, offenders
