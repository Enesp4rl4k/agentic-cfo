"""Faz 2: Gerçekçi GİB UBL-TR e-Fatura & e-Arşiv Motoru Doğrulama Testleri.

Doğrulamalar:
1. UBL-TR 1.2 / 2.1 Derin Ayrıştırıcı: PaymentMeans ve PaymentTerms'den kesin vade tarihi çıkarımı.
2. Tevkifatlı KDV, stopaj ve ÖTV kırılımlarının kuruşu kuruşuna (cents) ayrıştırılması.
3. Vadesi bulunmayan faturalarda ticari teamül (30 gün) tahmini vade ataması (date_is_estimated=True).
4. Toplu e-Fatura / e-Arşiv ZIP arşivi açma ve toplu ayrıştırma hattı (parse_ubl_zip).
5. Sıfır veri kaybı ve kuruş mutabakatı.
"""

from __future__ import annotations

import io
import zipfile
from datetime import date

import app.main  # noqa: F401
from app.parsers.invoice.ubl_tr import UBLTRInvoiceParser
from app.services.regional.ubl_parser import (
    extract_tax_breakdown,
    parse_ubl_zip,
    ubl_to_transaction_dict,
)

SAMPLE_UBL_WITH_PAYMENT_MEANS = """<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
    <cbc:UUID>550e8400-e29b-41d4-a716-446655440000</cbc:UUID>
    <cbc:ID>GIB2026000000101</cbc:ID>
    <cbc:IssueDate>2026-03-01</cbc:IssueDate>
    <cbc:InvoiceTypeCode>TEVKIFAT</cbc:InvoiceTypeCode>
    <cbc:DocumentCurrencyCode>TRY</cbc:DocumentCurrencyCode>

    <cac:AccountingSupplierParty>
        <cac:Party>
            <cac:PartyIdentification>
                <cbc:ID schemeID="VKN">1234567890</cbc:ID>
            </cac:PartyIdentification>
            <cac:PartyName>
                <cbc:Name>Tedarikçi A.Ş.</cbc:Name>
            </cac:PartyName>
        </cac:Party>
    </cac:AccountingSupplierParty>

    <cac:AccountingCustomerParty>
        <cac:Party>
            <cac:PartyIdentification>
                <cbc:ID schemeID="VKN">9876543210</cbc:ID>
            </cac:PartyIdentification>
            <cac:PartyName>
                <cbc:Name>Bizim Şirket Ltd. Şti.</cbc:Name>
            </cac:PartyName>
        </cac:Party>
    </cac:AccountingCustomerParty>

    <!-- Vade PaymentMeans içinde verilmiş -->
    <cac:PaymentMeans>
        <cbc:PaymentDueDate>2026-04-15</cbc:PaymentDueDate>
        <cbc:InstructionNote>Banka havalesi ile 45 gün vade</cbc:InstructionNote>
    </cac:PaymentMeans>

    <cac:TaxTotal>
        <cac:TaxSubtotal>
            <cbc:TaxableAmount currencyID="TRY">10000.00</cbc:TaxableAmount>
            <cbc:TaxAmount currencyID="TRY">2000.00</cbc:TaxAmount>
            <cbc:Percent>20</cbc:Percent>
            <cac:TaxCategory>
                <cac:TaxScheme>
                    <cbc:Name>Katma Değer Vergisi</cbc:Name>
                    <cbc:TaxTypeCode>0015</cbc:TaxTypeCode>
                </cac:TaxScheme>
            </cac:TaxCategory>
        </cac:TaxSubtotal>
        <cac:TaxSubtotal>
            <cbc:TaxableAmount currencyID="TRY">10000.00</cbc:TaxableAmount>
            <cbc:TaxAmount currencyID="TRY">500.00</cbc:TaxAmount>
            <cbc:Percent>5</cbc:Percent>
            <cac:TaxCategory>
                <cac:TaxScheme>
                    <cbc:Name>Özel Tüketim Vergisi</cbc:Name>
                    <cbc:TaxTypeCode>0071</cbc:TaxTypeCode>
                </cac:TaxScheme>
            </cac:TaxCategory>
        </cac:TaxSubtotal>
    </cac:TaxTotal>

    <!-- 5/10 KDV Tevkifatı (1.000 TL) -->
    <cac:WithholdingTaxTotal>
        <cbc:TaxAmount currencyID="TRY">1000.00</cbc:TaxAmount>
    </cac:WithholdingTaxTotal>

    <cac:LegalMonetaryTotal>
        <cbc:LineExtensionAmount currencyID="TRY">10000.00</cbc:LineExtensionAmount>
        <cbc:TaxExclusiveAmount currencyID="TRY">10000.00</cbc:TaxExclusiveAmount>
        <cbc:TaxInclusiveAmount currencyID="TRY">12500.00</cbc:TaxInclusiveAmount>
        <cbc:PayableAmount currencyID="TRY">11500.00</cbc:PayableAmount>
    </cac:LegalMonetaryTotal>
</Invoice>
"""

SAMPLE_UBL_NO_DUE_DATE = """<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
    <cbc:UUID>660e8400-e29b-41d4-a716-446655440001</cbc:UUID>
    <cbc:ID>GIB2026000000202</cbc:ID>
    <cbc:IssueDate>2026-05-10</cbc:IssueDate>
    <cbc:InvoiceTypeCode>SATIS</cbc:InvoiceTypeCode>
    <cbc:DocumentCurrencyCode>TRY</cbc:DocumentCurrencyCode>

    <cac:AccountingSupplierParty>
        <cac:Party>
            <cac:PartyIdentification>
                <cbc:ID schemeID="VKN">9876543210</cbc:ID>
            </cac:PartyIdentification>
            <cac:PartyName>
                <cbc:Name>Bizim Şirket Ltd. Şti.</cbc:Name>
            </cac:PartyName>
        </cac:Party>
    </cac:AccountingSupplierParty>

    <cac:AccountingCustomerParty>
        <cac:Party>
            <cac:PartyIdentification>
                <cbc:ID schemeID="VKN">5555555555</cbc:ID>
            </cac:PartyIdentification>
            <cac:PartyName>
                <cbc:Name>Müşteri Ltd.</cbc:Name>
            </cac:PartyName>
        </cac:Party>
    </cac:AccountingCustomerParty>

    <cac:TaxTotal>
        <cac:TaxSubtotal>
            <cbc:TaxableAmount currencyID="TRY">5000.00</cbc:TaxableAmount>
            <cbc:TaxAmount currencyID="TRY">1000.00</cbc:TaxAmount>
            <cbc:Percent>20</cbc:Percent>
            <cac:TaxCategory>
                <cac:TaxScheme>
                    <cbc:Name>Katma Değer Vergisi</cbc:Name>
                    <cbc:TaxTypeCode>0015</cbc:TaxTypeCode>
                </cac:TaxScheme>
            </cac:TaxCategory>
        </cac:TaxSubtotal>
    </cac:TaxTotal>

    <cac:LegalMonetaryTotal>
        <cbc:LineExtensionAmount currencyID="TRY">5000.00</cbc:LineExtensionAmount>
        <cbc:TaxInclusiveAmount currencyID="TRY">6000.00</cbc:TaxInclusiveAmount>
        <cbc:PayableAmount currencyID="TRY">6000.00</cbc:PayableAmount>
    </cac:LegalMonetaryTotal>
</Invoice>
"""


def test_payment_means_due_date_resolution():
    """2.1: PaymentMeans içindeki PaymentDueDate ve notu eksiksiz okunmalı."""
    inv = UBLTRInvoiceParser.parse_xml(
        SAMPLE_UBL_WITH_PAYMENT_MEANS.encode("utf-8"),
        own_vkn="9876543210",  # Biz müşteriyiz -> purchase
    )
    assert inv.payment_due_date == date(2026, 4, 15)
    assert "45 gün vade" in inv.payment_note
    assert inv.direction == "purchase"
    assert inv.invoice_number == "GIB2026000000101"


def test_tax_breakdown_withholding_and_otv():
    """2.1: KDV, ÖTV ve Tevkifat kuruşu kuruşuna tamsayı olarak ayrıştırılmalı."""
    inv = UBLTRInvoiceParser.parse_xml(
        SAMPLE_UBL_WITH_PAYMENT_MEANS.encode("utf-8"),
        own_vkn="9876543210",
    )
    breakdown = extract_tax_breakdown(inv)

    assert breakdown.matrah_cents == 1000000  # 10.000,00 TL
    assert breakdown.kdv_cents == 200000  # 2.000,00 TL KDV
    assert breakdown.otv_cents == 50000  # 500,00 TL ÖTV (0071)
    assert breakdown.stopaj_cents == 100000  # 1.000,00 TL Tevkifat
    assert breakdown.payable_cents == 1150000  # 11.500,00 TL Ödenecek net tutar


def test_fallback_due_date_for_unstated_invoices():
    """2.1: Vadesi belirtilmeyen faturada ticari teamül (30 gün) atanmalı ve date_is_estimated olmalı."""
    inv = UBLTRInvoiceParser.parse_xml(
        SAMPLE_UBL_NO_DUE_DATE.encode("utf-8"),
        own_vkn="9876543210",  # Biz satıcıyız -> sale
    )
    assert inv.payment_due_date is None

    tx_dict = ubl_to_transaction_dict(inv, default_due_days=30)
    assert tx_dict["due_date"] == "2026-06-09"  # 2026-05-10 + 30 gün
    assert tx_dict["date_is_estimated"] is True
    assert "30 günlük ticari teamül" in tx_dict["payment_note"]
    assert tx_dict["amount_cents"] == 600000
    assert tx_dict["kdv_cents"] == 100000
    assert tx_dict["type"] == "income"
    assert tx_dict["category"] == "revenue"


def test_parse_ubl_zip_batch():
    """2.2: Zip arşivi içindeki birden fazla e-Fatura XML'ini toplu ve güvenle ayrıştırma."""
    # Bellekte test ZIP'i oluştur
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zf:
        zf.writestr("fatura1.xml", SAMPLE_UBL_WITH_PAYMENT_MEANS.encode("utf-8"))
        zf.writestr("fatura2.xml", SAMPLE_UBL_NO_DUE_DATE.encode("utf-8"))
        zf.writestr("readme.txt", b"GIB Fatura Listesi")

    invoices = parse_ubl_zip(zip_buffer.getvalue(), own_vkn="9876543210")
    assert len(invoices) == 2

    inv_nums = {inv.invoice_number for inv in invoices}
    assert "GIB2026000000101" in inv_nums
    assert "GIB2026000000202" in inv_nums
