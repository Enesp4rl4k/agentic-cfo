"""
Tests for GİB UBL-TR e-Fatura / e-Arşiv XML ingestion and open banking reconciliation (Phase 1).
"""
from __future__ import annotations

import os
import tempfile

import pytest

from app.agents.orchestrator import run_cfo_pipeline
from app.agents.state import AgentRunConfig, CFOState
from app.parsers.invoice.ubl_tr import UBLTRInvoiceParser

SAMPLE_UBL_TR_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
    <cbc:UUID>e5b7a120-1234-4567-89ab-cdef01234567</cbc:UUID>
    <cbc:ID>GIB2024000000042</cbc:ID>
    <cbc:InvoiceTypeCode>SATIS</cbc:InvoiceTypeCode>
    <cbc:ProfileID>TICARIFATURA</cbc:ProfileID>
    <cbc:IssueDate>2024-03-15</cbc:IssueDate>
    <cbc:DocumentCurrencyCode>TRY</cbc:DocumentCurrencyCode>

    <cac:AccountingSupplierParty>
        <cac:Party>
            <cac:PartyIdentification>
                <cbc:ID schemeID="VKN">1234567890</cbc:ID>
            </cac:PartyIdentification>
            <cac:PartyName>
                <cbc:Name>ACME Yazilim ve Danismanlik A.S.</cbc:Name>
            </cac:PartyName>
        </cac:Party>
    </cac:AccountingSupplierParty>

    <cac:AccountingCustomerParty>
        <cac:Party>
            <cac:PartyIdentification>
                <cbc:ID schemeID="VKN">9876543210</cbc:ID>
            </cac:PartyIdentification>
            <cac:PartyName>
                <cbc:Name>Beta Holding A.S.</cbc:Name>
            </cac:PartyName>
        </cac:Party>
    </cac:AccountingCustomerParty>

    <cac:TaxTotal>
        <cbc:TaxAmount currencyID="TRY">20000.00</cbc:TaxAmount>
        <cac:TaxSubtotal>
            <cbc:TaxableAmount currencyID="TRY">100000.00</cbc:TaxableAmount>
            <cbc:TaxAmount currencyID="TRY">20000.00</cbc:TaxAmount>
            <cbc:Percent>20</cbc:Percent>
            <cac:TaxCategory>
                <cac:TaxScheme>
                    <cbc:Name>KDV</cbc:Name>
                    <cbc:TaxTypeCode>0015</cbc:TaxTypeCode>
                </cac:TaxScheme>
            </cac:TaxCategory>
        </cac:TaxSubtotal>
    </cac:TaxTotal>

    <cac:LegalMonetaryTotal>
        <cbc:LineExtensionAmount currencyID="TRY">100000.00</cbc:LineExtensionAmount>
        <cbc:TaxExclusiveAmount currencyID="TRY">100000.00</cbc:TaxExclusiveAmount>
        <cbc:TaxInclusiveAmount currencyID="TRY">120000.00</cbc:TaxInclusiveAmount>
        <cbc:PayableAmount currencyID="TRY">120000.00</cbc:PayableAmount>
    </cac:LegalMonetaryTotal>

    <cac:InvoiceLine>
        <cbc:ID>1</cbc:ID>
        <cbc:InvoicedQuantity unitCode="C62">1</cbc:InvoicedQuantity>
        <cbc:LineExtensionAmount currencyID="TRY">100000.00</cbc:LineExtensionAmount>
        <cac:Item>
            <cbc:Name>Yillik Kurumsal Yazilim Lisansi</cbc:Name>
        </cac:Item>
        <cac:Price>
            <cbc:PriceAmount currencyID="TRY">100000.00</cbc:PriceAmount>
        </cac:Price>
    </cac:InvoiceLine>
</Invoice>
"""


def test_ubl_tr_parser_standalone():
    """UBLTRInvoiceParser correctly extracts Turkish e-Invoice XML structure."""
    invoice = UBLTRInvoiceParser.parse_xml(SAMPLE_UBL_TR_XML)
    assert invoice.invoice_number == "GIB2024000000042"
    assert invoice.invoice_type == "SATIS"
    assert invoice.payable_amount == 120000
    assert invoice.supplier.title == "ACME Yazilim ve Danismanlik A.S."
    assert invoice.customer.title == "Beta Holding A.S."
    assert len(invoice.tax_subtotals) >= 1
    assert invoice.tax_subtotals[0].tax_amount == 20000


@pytest.mark.asyncio
async def test_cfo_pipeline_runs_with_ubl_tr_xml(monkeypatch):
    """CFO pipeline processes native GİB UBL-TR XML end to end.

    The supplier VKN on this invoice is ours, so the pipeline can settle the
    direction and post it. It used to assert a flat confidence of 1.0, which is
    what let an invoice booked on a guessed side clear the review gate.
    """
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "gib_vkn", "1234567890", raising=False)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".xml", delete=False, encoding="utf-8") as f:
        f.write(SAMPLE_UBL_TR_XML)
        xml_path = f.name

    try:
        run_config = AgentRunConfig(dry_run=False, require_review=False, auto_proceed_min_confidence=0.0)
        result: CFOState = await run_cfo_pipeline(
            job_id="test-efatura-001",
            file_path=xml_path,
            file_type="xml",
            run_config=run_config,
        )

        assert result.get("halted") is False
        txs = result.get("transactions") or []
        assert len(txs) >= 1
        assert txs[0]["amount_cents"] == 12000000  # 120,000 TRY = 12,000,000 cents
        assert txs[0]["type"] == "income"      # we issued it
        assert txs[0]["confidence"] == 0.95     # settled by VKN, not by type code
        assert "GIB2024000000042" in txs[0]["description"]

    finally:
        if os.path.exists(xml_path):
            os.unlink(xml_path)


@pytest.mark.asyncio
async def test_ubl_invoice_from_a_stranger_is_held_for_review(monkeypatch):
    """Neither party is us, so the direction is a coin flip on the sign.

    The pipeline still ingests the row — a withheld invoice is not a discarded
    one — but below the gate, where a human decides which way it goes.
    """
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "gib_vkn", "5555555555", raising=False)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".xml", delete=False, encoding="utf-8"
    ) as f:
        f.write(SAMPLE_UBL_TR_XML)
        xml_path = f.name

    try:
        result: CFOState = await run_cfo_pipeline(
            job_id="test-efatura-002",
            file_path=xml_path,
            file_type="xml",
            run_config=AgentRunConfig(
                dry_run=False, require_review=False, auto_proceed_min_confidence=0.0
            ),
        )
        txs = result.get("transactions") or []
        assert len(txs) >= 1
        assert txs[0]["confidence"] < 0.80, "yönü belirsiz fatura kapıdan geçmemeli"
        assert "unknown" in txs[0]["raw_text"]
    finally:
        if os.path.exists(xml_path):
            os.unlink(xml_path)
