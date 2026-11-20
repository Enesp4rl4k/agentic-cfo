"""A PDF invoice is recognised as an invoice, not as a Paraşüt export.

Measured on the repo's own samples, three of four ordinary invoice texts were
sent by `ParserRegistry.detect` to the Paraşüt parser: its marker "Fatura No" is
on nearly every invoice, and the invoice parser is last in the order. A Paraşüt
parse of invoice prose yields no rows, so the document fell through to LLM
extraction: not repeatable, and with no VKN-based direction at all.

Reordering would have fixed the invoices and broken real Paraşüt exports, which
carry a "Fatura No" column too. So the Paraşüt parser now recognises *structure*:
its brand, or a delimited header row naming one of its columns. A word in prose
is no longer enough. Both directions are held here.
"""

from __future__ import annotations

import pytest

from app.parsers.accounting.parasut import ParasutParser
from app.parsers.invoice import InvoiceBatchParser, TurkishInvoiceParser
from app.parsers.registry import ParserRegistry
from tests.test_parsers import test_ocr_and_invoice as O

INVOICES = ["GIB_EFATURA_TEXT", "GENERAL_INVOICE_TEXT", "PURCHASE_INVOICE_TEXT", "_OCR_INVOICE"]


@pytest.mark.parametrize("name", INVOICES)
def test_an_ordinary_invoice_text_is_read_by_the_invoice_parser(name):
    assert ParserRegistry.detect(getattr(O, name)) is TurkishInvoiceParser


def test_several_invoices_in_one_document_are_read_by_the_batch_parser():
    text = O._OCR_INVOICE + "\n--- Page 2 ---\n" + O._OCR_INVOICE.replace("ABC2024000000123", "ABC2024000000124")
    assert ParserRegistry.detect(text) is InvoiceBatchParser


@pytest.mark.parametrize("text", [
    # a real Paraşüt export, header row only a column list, no brand
    "Tarih,Fatura No,Müşteri/Tedarikçi,Açıklama,Tutar,KDV,Toplam,Durum\n"
    "2024-01-05,F-1,ACME,Hizmet,100,20,120,Ödendi\n",
    "İşlem Tarihi;Tip;Kategori;Tutar\n05.01.2024;Gelir;Satış;100,00\n",
    "Fatura No;Hesap Adı;KDV Tutarı\nF-1;Banka;20,00\n",
])
def test_a_parasut_export_is_still_a_parasut_export(text):
    assert ParasutParser.can_parse(text)
    assert ParserRegistry.detect(text) is ParasutParser


@pytest.mark.parametrize("text", ["Paraşüt - İşlem Raporu", "app.parasut.com export", "PARASUT raporu"])
def test_the_brand_alone_is_enough(text):
    assert ParasutParser.can_parse(text)


@pytest.mark.parametrize("text", [
    "Fatura No: FTR-2024-001\nFatura Tarihi: 15.03.2024\nToplam: 120,00",   # prose
    "Hizmet Adı   Miktar   KDV Tutarı\nYazılım   1   20,00",                 # space-aligned table
    "Ödeme için Hesap Adı: Demir Yazılım A.Ş.",                              # a word in a sentence
    "",
])
def test_a_marker_word_in_prose_is_not_a_parasut_export(text):
    assert not ParasutParser.can_parse(text)
