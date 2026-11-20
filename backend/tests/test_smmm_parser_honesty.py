"""Plan M0, D2 — nothing invented: what a parser cannot read, it holds.

* An invoice with no (or a garbled) issue date used to be dated 2024-01-01 or
  today and posted. It is held for review with no date instead.
* A bank statement is a bank statement even when it contains the words an
  accounting export also contains ("Borç", "Alacak", "Hesap Hareketleri").
"""

from __future__ import annotations

import re

import pytest

from app.parsers.invoice.ubl_tr import UBLTRInvoiceParser
from app.parsers.registry import ParserRegistry
from tests.test_parsers.test_ocr_and_invoice import SAMPLE_UBL_TR_XML


def _xml_with_date(replacement: str | None) -> str:
    xml = SAMPLE_UBL_TR_XML if isinstance(SAMPLE_UBL_TR_XML, str) else SAMPLE_UBL_TR_XML.decode()
    pattern = r"<cbc:IssueDate>[^<]*</cbc:IssueDate>"
    assert re.search(pattern, xml), "fixture has no IssueDate to remove"
    return re.sub(pattern, "" if replacement is None else f"<cbc:IssueDate>{replacement}</cbc:IssueDate>", xml)


@pytest.mark.parametrize("raw", [None, "", "31/13/2026", "not-a-date"])
def test_invoice_without_a_readable_date_is_held_not_dated(raw):
    parsed = UBLTRInvoiceParser.parse_xml(_xml_with_date(raw), own_vkn="1234567890")
    assert parsed.issue_date is None
    assert parsed.needs_review
    assert "tarih" in parsed.posting_note.lower()


def test_invoice_with_a_date_is_unchanged():
    parsed = UBLTRInvoiceParser.parse_xml(SAMPLE_UBL_TR_XML, own_vkn="1234567890")
    assert parsed.issue_date is not None
    assert not parsed.needs_review


@pytest.mark.parametrize(
    "text, bank",
    [
        ("T.C. ZİRAAT BANKASI Hesap Hareketleri Tarih Açıklama Borç Alacak Bakiye", "Ziraat"),
        ("GARANTİ BBVA Hesap Hareketleri Borç Alacak", "Garanti"),
        ("QNB Finansbank Hesap Ekstresi GİRİŞ ÇIKIŞ Bakiye", "QNB"),
    ],
)
def test_bank_statement_is_not_mistaken_for_an_accounting_export(text, bank):
    cls = ParserRegistry.detect(text)
    assert cls is not None
    assert bank.lower() in cls.bank_display_name.lower(), cls.bank_display_name
