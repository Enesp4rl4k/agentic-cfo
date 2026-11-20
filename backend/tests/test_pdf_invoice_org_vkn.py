"""A PDF invoice is read against the organisation's own VKN, not the deployment's.

The UBL-TR parser got its VKN from the organisation (M1); the parser for PDF and
OCR invoices still read the one global `GIB_VKN`. With an accountant's clients as
organisations of their own, every company but one then read its invoices against
somebody else's number: held for review when neither party matched, or booked on
the wrong side when the global company happened to be a party.

The rule held here is the one the UBL path already follows: an explicit VKN is
used as given; an explicit *empty* one (a client that has none yet) is NOT quietly
replaced by the global number; only "not told" (None) falls back to it.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.parsers.invoice import InvoiceBatchParser, TurkishInvoiceParser

SELLER, BUYER = "1234567890", "9876543210"

INVOICE = """
FATURA
Fatura No: ABC2024000000123
Fatura Tarihi: 15.03.2024
Satıcı: Demir Yazılım A.Ş.
Vergi Kimlik No: 1234567890
Alıcı: Global Lojistik Ltd. Şti.
Vergi No: 9876543210
Mal Hizmet Tutarı: 100.000,00
KDV Dahil Toplam: 120.000,00
ETTN: b3d9a2f1-7c44-4e18-9a2b-5f6e1c0d8a44
"""

SECOND = INVOICE.replace("ABC2024000000123", "ABC2024000000124").replace(
    "b3d9a2f1-7c44-4e18-9a2b-5f6e1c0d8a44", "c4e0b3a2-8d55-4f29-8b3c-6a7f2d1e9b55"
)


def _parse(parser, text=INVOICE, global_vkn=""):
    with patch("app.config.get_settings") as gs:
        gs.return_value.gib_vkn = global_vkn
        return parser.parse(text)


def test_the_organisations_vkn_decides_the_direction():
    assert _parse(TurkishInvoiceParser(own_vkn=SELLER)).transactions[0].tx_type == "income"
    assert _parse(TurkishInvoiceParser(own_vkn=BUYER)).transactions[0].tx_type == "expense"


def test_an_explicit_vkn_beats_a_global_one_that_says_the_opposite():
    # The deployment's number is the buyer's; this organisation is the seller.
    tx = _parse(TurkishInvoiceParser(own_vkn=SELLER), global_vkn=BUYER).transactions[0]
    assert tx.tx_type == "income" and tx.confidence > 0.60


def test_a_client_with_no_vkn_is_held_not_read_against_the_global_number():
    # Empty means "this organisation has none yet", not "not told".
    stmt = _parse(TurkishInvoiceParser(own_vkn=""), global_vkn=SELLER)
    assert stmt.transactions[0].confidence <= 0.60
    assert any("yönü kesin değil" in w for w in stmt.parse_warnings)


def test_not_told_falls_back_to_the_global_vkn_as_before():
    tx = _parse(TurkishInvoiceParser(), global_vkn=BUYER).transactions[0]
    assert tx.tx_type == "expense" and tx.confidence > 0.60


def test_the_batch_parser_passes_the_vkn_to_every_invoice():
    text = INVOICE + "\n--- Page 2 ---\n" + SECOND
    stmt = _parse(InvoiceBatchParser(own_vkn=SELLER), text, global_vkn=BUYER)
    assert len(stmt.transactions) == 2
    assert {t.tx_type for t in stmt.transactions} == {"income"}


@pytest.mark.asyncio
async def test_ingestion_reads_a_pdf_invoice_against_the_organisations_vkn(tmp_path, monkeypatch):
    from app.agents import data_ingestion
    from app.agents.state import AgentRunConfig
    from app.config import get_settings

    pdf = tmp_path / "fatura.pdf"
    pdf.write_bytes(b"%PDF-1.4 not really a pdf")
    monkeypatch.setattr(data_ingestion, "_read_pdf", lambda _p: INVOICE)
    monkeypatch.setattr(data_ingestion, "_pdf_embedded_xml", lambda _p: [])
    monkeypatch.setattr(get_settings(), "gib_vkn", SELLER)  # the deployment says seller

    async def org_is_the_buyer(_org_id):
        return BUYER

    monkeypatch.setattr("app.services.org_identity.own_vkn", org_is_the_buyer)
    res = await data_ingestion._belgeyi_al(
        str(pdf), "pdf", {"org_id": "org-1", "job_id": "j"}, AgentRunConfig()
    )
    txs = res.patch["transactions"]
    assert [t["type"] for t in txs] == ["expense"], "read against the deployment's number, not the organisation's"
