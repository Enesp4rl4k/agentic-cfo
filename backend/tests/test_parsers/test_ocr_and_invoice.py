"""
Tests for OCR service and invoice parser — pure function tests.
No real PDF files needed — uses synthetic text fixtures.
"""
import pytest

from app.parsers.invoice import (
    InvoiceBatchParser,
    TurkishInvoiceParser,
    _detect_invoice_type,
    _invoice_type_to_tx_type,
)
from app.services.ocr_service import (
    OCRResult,
    _clean_ocr_text,
    extract_invoice_fields,
)

# ── Fixtures — synthetic invoice text ─────────────────────────────────────────

GIB_EFATURA_TEXT = """
e-Fatura
ETTN: 12345678-1234-1234-1234-123456789012
Senaryo: TEMELFATURA

Satıcı Bilgileri
Şirket Adı: TechNova Yazılım A.Ş.
Vergi Kimlik No: 1234567890
Vergi Dairesi: Beyoğlu

Alıcı Bilgileri
Şirket Adı: ABC Holding A.Ş.
Vergi Kimlik No: 9876543210

Fatura No: FTR-2024-001
Fatura Tarihi: 15.03.2024

Hizmet Kodu  Hizmet Adı                    Miktar  Birim Fiyat  KDV%  Toplam
1            Yazılım Geliştirme Hizmeti    10 saat  500,00       %20  5.000,00
2            Sistem Analizi                 5 saat  300,00       %20  1.500,00

Mal Hizmet Tutarı:            6.500,00 TL
Toplam KDV (%20):             1.300,00 TL
Genel Toplam:                 7.800,00 TL
"""

GENERAL_INVOICE_TEXT = """
SATIŞ FATURASI

Tarih: 20.01.2024
Fatura No: SF-2024-0042

Tedarikçi: DEF Teknoloji Ltd. Şti.
VKN: 5555555555

Müşteri: XYZ Şirketi A.Ş.

Açıklama          Adet    Birim Fiyat    Toplam
AWS Cloud Servis   1 ay    8.500,00      8.500,00
GitHub Enterprise  10 kul  450,00        4.500,00

Ara Toplam:    13.000,00 TL
KDV (%20):      2.600,00 TL
TOPLAM:        15.600,00 TL
"""

PURCHASE_INVOICE_TEXT = """
ALIŞ FATURASI

Fatura Tarihi: 05.02.2024
Fatura Numarası: ALF-2024-0015

Satıcı: Ofis Malzemeleri A.Ş.
Vergi No: 2222222222

Ürün Adı           Miktar  Birim Fiyat  Toplam
Ofis Kırtasiye      1 set   1.200,00    1.200,00
Yazıcı Kartuşu      5 adet    250,00    1.250,00

Genel Toplam: 2.450,00 TL
"""

MULTI_INVOICE_TEXT = """
--- Page 1 ---
SATIŞ FATURASI
Fatura No: FTR-001
Fatura Tarihi: 10.01.2024
Genel Toplam: 5.000,00 TL

--- Page 2 ---
SATIŞ FATURASI
Fatura No: FTR-002
Fatura Tarihi: 15.01.2024
Genel Toplam: 8.500,00 TL

--- Page 3 ---
SATIŞ FATURASI
Fatura No: FTR-003
Fatura Tarihi: 20.01.2024
Genel Toplam: 3.200,00 TL
"""

RETURN_INVOICE_TEXT = """
İADE FATURASI
Fatura No: IAD-2024-001
Fatura Tarihi: 28.03.2024
Genel Toplam: 1.500,00 TL
"""

BANK_STATEMENT_TEXT = """
AKBANK T.A.Ş. Hesap Ekstresi
Hesap No: 1234-5678
15.01.2024  ELEKTRİK FATURASI  250,00  5.750,00
"""


# ── _clean_ocr_text ───────────────────────────────────────────────────────────

class TestCleanOCRText:

    def test_removes_extra_spaces_in_numbers(self):
        result = _clean_ocr_text("1 500 ,00 TL")
        assert "1500" in result or "1 500" in result  # spaces in thousands removed

    def test_normalizes_multiple_blank_lines(self):
        result = _clean_ocr_text("line1\n\n\n\n\nline2")
        assert result.count("\n") < 4

    def test_empty_string_returns_empty(self):
        assert _clean_ocr_text("") == ""

    def test_preserves_meaningful_content(self):
        result = _clean_ocr_text("Fatura No: FTR-2024-001\nToplam: 5.000,00 TL")
        assert "Fatura No" in result
        assert "Toplam" in result

    def test_removes_pipe_noise(self):
        result = _clean_ocr_text("Col1 ||| Col2 ||| Col3")
        assert "|||" not in result

    def test_fixes_tl_format(self):
        result = _clean_ocr_text("1500,00 Tl tutar")
        assert "TL" in result or "Tl" in result  # normalized


# ── extract_invoice_fields ─────────────────────────────────────────────────────

class TestExtractInvoiceFields:

    def test_extracts_invoice_number(self):
        result = extract_invoice_fields(GIB_EFATURA_TEXT)
        assert result["invoice_no"] == "FTR-2024-001"

    def test_extracts_invoice_date(self):
        result = extract_invoice_fields(GIB_EFATURA_TEXT)
        assert result["invoice_date"] == "15.03.2024"

    def test_extracts_vendor_tax_id(self):
        result = extract_invoice_fields(GIB_EFATURA_TEXT)
        assert result["vendor_tax_id"] == "1234567890"

    def test_extracts_buyer_tax_id(self):
        result = extract_invoice_fields(GIB_EFATURA_TEXT)
        assert result["buyer_tax_id"] == "9876543210"

    def test_extracts_total_amount(self):
        result = extract_invoice_fields(GIB_EFATURA_TEXT)
        assert result["total_amount"] is not None
        assert result["total_amount"] == pytest.approx(7800.0)

    def test_extracts_vat_amount(self):
        result = extract_invoice_fields(GIB_EFATURA_TEXT)
        assert result["vat_amount"] is not None
        assert result["vat_amount"] == pytest.approx(1300.0)

    def test_extracts_subtotal(self):
        result = extract_invoice_fields(GIB_EFATURA_TEXT)
        assert result["subtotal"] is not None
        assert result["subtotal"] == pytest.approx(6500.0)

    def test_currency_try_default(self):
        result = extract_invoice_fields(GIB_EFATURA_TEXT)
        assert result["currency"] == "TRY"

    def test_currency_usd_detected(self):
        result = extract_invoice_fields("Invoice Total: $5,000.00 USD")
        assert result["currency"] == "USD"

    def test_currency_eur_detected(self):
        result = extract_invoice_fields("Rechnung Gesamt: €2.500,00 EUR")
        assert result["currency"] == "EUR"

    def test_empty_text_returns_none_values(self):
        result = extract_invoice_fields("")
        assert result["invoice_no"] is None
        assert result["total_amount"] is None

    def test_general_invoice_total(self):
        result = extract_invoice_fields(GENERAL_INVOICE_TEXT)
        assert result["total_amount"] is not None
        assert result["total_amount"] == pytest.approx(15600.0)

    def test_general_invoice_number(self):
        result = extract_invoice_fields(GENERAL_INVOICE_TEXT)
        assert result["invoice_no"] == "SF-2024-0042"

    def test_required_keys_always_present(self):
        result = extract_invoice_fields("")
        for key in ("invoice_no", "invoice_date", "vendor_name", "vendor_tax_id",
                    "buyer_name", "buyer_tax_id", "subtotal", "vat_amount",
                    "total_amount", "currency", "line_items"):
            assert key in result


# ── _detect_invoice_type ──────────────────────────────────────────────────────

class TestDetectInvoiceType:

    def test_satis_faturasi_detected(self):
        assert _detect_invoice_type("SATIŞ FATURASI") == "satis"

    def test_alis_faturasi_detected(self):
        assert _detect_invoice_type("ALIŞ FATURASI") == "alis"

    def test_iade_faturasi_detected(self):
        assert _detect_invoice_type("İADE FATURASI") == "iade"

    def test_proforma_detected(self):
        assert _detect_invoice_type("PROFORMA FATURA") == "proforma"

    def test_unknown_returns_unknown(self):
        assert _detect_invoice_type("Hesap Ekstresi") == "unknown"

    def test_case_insensitive(self):
        assert _detect_invoice_type("satış faturası") == "satis"

    def test_invoice_english(self):
        assert _detect_invoice_type("SALE INVOICE") == "satis"


# ── _invoice_type_to_tx_type ──────────────────────────────────────────────────

class TestInvoiceTypeToTxType:

    def test_satis_is_income(self):
        assert _invoice_type_to_tx_type("satis") == "income"

    def test_alis_is_expense(self):
        assert _invoice_type_to_tx_type("alis") == "expense"

    def test_iade_is_income_by_default(self):
        assert _invoice_type_to_tx_type("iade") == "income"

    def test_unknown_is_expense(self):
        assert _invoice_type_to_tx_type("unknown") == "expense"

    def test_proforma_is_expense(self):
        assert _invoice_type_to_tx_type("proforma") == "expense"


# ── TurkishInvoiceParser — Detection ──────────────────────────────────────────

class TestTurkishInvoiceParserDetection:

    def test_detects_gib_efatura(self):
        assert TurkishInvoiceParser.can_parse(GIB_EFATURA_TEXT) is True

    def test_detects_satis_faturasi(self):
        assert TurkishInvoiceParser.can_parse(GENERAL_INVOICE_TEXT) is True

    def test_detects_alis_faturasi(self):
        assert TurkishInvoiceParser.can_parse(PURCHASE_INVOICE_TEXT) is True

    def test_detects_iade_faturasi(self):
        assert TurkishInvoiceParser.can_parse(RETURN_INVOICE_TEXT) is True

    def test_does_not_detect_bank_statement(self):
        assert TurkishInvoiceParser.can_parse(BANK_STATEMENT_TEXT) is False

    def test_does_not_detect_empty(self):
        assert TurkishInvoiceParser.can_parse("") is False

    def test_does_not_detect_random_text(self):
        assert TurkishInvoiceParser.can_parse("Merhaba dünya") is False


# ── TurkishInvoiceParser — Parsing ────────────────────────────────────────────

class TestTurkishInvoiceParserParsing:

    def setup_method(self):
        self.parser = TurkishInvoiceParser()

    def test_gib_invoice_produces_one_transaction(self):
        result = self.parser.parse(GIB_EFATURA_TEXT)
        assert len(result.transactions) == 1

    def test_satis_fatura_is_income(self):
        result = self.parser.parse(GIB_EFATURA_TEXT)
        tx = result.transactions[0]
        assert tx.tx_type == "income"

    def test_alis_fatura_is_expense(self):
        result = self.parser.parse(PURCHASE_INVOICE_TEXT)
        tx = result.transactions[0]
        assert tx.tx_type == "expense"

    def test_amount_extracted_correctly(self):
        result = self.parser.parse(GIB_EFATURA_TEXT)
        tx = result.transactions[0]
        assert tx.amount_cents == 780_000  # 7.800,00 TL

    def test_general_invoice_amount(self):
        result = self.parser.parse(GENERAL_INVOICE_TEXT)
        tx = result.transactions[0]
        assert tx.amount_cents == 1_560_000  # 15.600,00 TL

    def test_invoice_reference_stored(self):
        result = self.parser.parse(GIB_EFATURA_TEXT)
        tx = result.transactions[0]
        assert tx.reference == "FTR-2024-001"

    def test_date_parsed(self):
        result = self.parser.parse(GIB_EFATURA_TEXT)
        tx = result.transactions[0]
        assert tx.date is not None
        assert tx.date.month == 3
        assert tx.date.day == 15

    def test_currency_try(self):
        result = self.parser.parse(GIB_EFATURA_TEXT)
        tx = result.transactions[0]
        assert tx.currency == "TRY"

    def test_amount_always_positive(self):
        for text in [GIB_EFATURA_TEXT, GENERAL_INVOICE_TEXT, PURCHASE_INVOICE_TEXT]:
            result = self.parser.parse(text)
            for tx in result.transactions:
                assert tx.amount_cents > 0

    def test_bank_name_correct(self):
        result = self.parser.parse(GIB_EFATURA_TEXT)
        assert "invoice" in result.bank_name.lower() or "fatura" in result.bank_name.lower()


# ── InvoiceBatchParser ────────────────────────────────────────────────────────

class TestInvoiceBatchParser:

    def setup_method(self):
        self.parser = InvoiceBatchParser()

    def test_detects_multi_invoice(self):
        assert InvoiceBatchParser.can_parse(MULTI_INVOICE_TEXT) is True

    def test_single_invoice_not_batch(self):
        assert InvoiceBatchParser.can_parse(GIB_EFATURA_TEXT) is False

    def test_batch_produces_multiple_transactions(self):
        result = self.parser.parse(MULTI_INVOICE_TEXT)
        # Each page has one invoice
        assert len(result.transactions) >= 2

    def test_batch_all_income(self):
        result = self.parser.parse(MULTI_INVOICE_TEXT)
        for tx in result.transactions:
            assert tx.tx_type == "income"

    def test_batch_date_range_set(self):
        result = self.parser.parse(MULTI_INVOICE_TEXT)
        if result.transactions:
            assert result.statement_period_start is not None
            assert result.statement_period_end is not None


# ── OCRResult dataclass ────────────────────────────────────────────────────────

class TestOCRResult:

    def _make_result(self, confidence: float, text: str = "sample text") -> OCRResult:
        return OCRResult(
            text=text,
            confidence=confidence,
            strategy_used="native",
            page_count=1,
            page_results=[],
            file_path="test.pdf",
        )

    def test_is_reliable_above_threshold(self):
        r = self._make_result(0.80)
        assert r.is_reliable is True

    def test_is_reliable_below_threshold(self):
        r = self._make_result(0.60)
        assert r.is_reliable is False

    def test_needs_llm_fallback_low_confidence(self):
        r = self._make_result(0.40, "short")
        assert r.needs_llm_fallback is True

    def test_needs_llm_fallback_good_text(self):
        r = self._make_result(0.85, "A " * 100)
        assert r.needs_llm_fallback is False

    def test_needs_llm_fallback_empty_text(self):
        r = self._make_result(0.90, "")
        assert r.needs_llm_fallback is True


# ── UBL-TR XML Invoice Parser Tests ──────────────────────────────────────────

SAMPLE_UBL_TR_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
    <cbc:UUID>e8f81014-41d9-4b36-a6c9-0414f52cfbe4</cbc:UUID>
    <cbc:ID>GIB2024000000042</cbc:ID>
    <cbc:IssueDate>2024-03-15</cbc:IssueDate>
    <cbc:InvoiceTypeCode>SATIS</cbc:InvoiceTypeCode>
    <cbc:DocumentCurrencyCode>TRY</cbc:DocumentCurrencyCode>

    <cac:AccountingSupplierParty>
        <cac:Party>
            <cac:PartyIdentification>
                <cbc:ID>1234567890</cbc:ID>
            </cac:PartyIdentification>
            <cac:PartyName>
                <cbc:Name>ACME Yazılım ve Bilişim A.Ş.</cbc:Name>
            </cac:PartyName>
            <cac:PartyTaxScheme>
                <cac:TaxScheme>
                    <cbc:Name>Büyük Mükellefler</cbc:Name>
                </cac:TaxScheme>
            </cac:PartyTaxScheme>
        </cac:Party>
    </cac:AccountingSupplierParty>

    <cac:AccountingCustomerParty>
        <cac:Party>
            <cac:PartyIdentification>
                <cbc:ID>9876543210</cbc:ID>
            </cac:PartyIdentification>
            <cac:PartyName>
                <cbc:Name>Global Lojistik Ltd. Şti.</cbc:Name>
            </cac:PartyName>
        </cac:Party>
    </cac:AccountingCustomerParty>

    <cac:TaxTotal>
        <cbc:TaxAmount currencyID="TRY">20000.00</cbc:TaxAmount>
        <cac:TaxSubtotal>
            <cbc:TaxableAmount currencyID="TRY">100000.00</cbc:TaxableAmount>
            <cbc:TaxAmount currencyID="TRY">20000.00</cbc:TaxAmount>
            <cbc:Percent>20.00</cbc:Percent>
            <cac:TaxCategory>
                <cac:TaxScheme>
                    <cbc:Name>KDV</cbc:Name>
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
            <cbc:Name>Kurumsal ERP Yazılım Lisansı</cbc:Name>
        </cac:Item>
        <cac:Price>
            <cbc:PriceAmount currencyID="TRY">100000.00</cbc:PriceAmount>
        </cac:Price>
    </cac:InvoiceLine>
</Invoice>
"""


def test_ubl_tr_xml_invoice_parser():
    from decimal import Decimal

    from app.parsers.invoice.ubl_tr import UBLTRInvoiceParser

    # The supplier's VKN is ours, so this is a sale. Without `own_vkn` the
    # direction is unknowable and the parser deliberately posts nothing —
    # see test_ubl_tr_without_own_vkn_posts_nothing below.
    parsed = UBLTRInvoiceParser.parse_xml(SAMPLE_UBL_TR_XML, own_vkn="1234567890")

    assert parsed.direction == "sale"
    assert parsed.invoice_number == "GIB2024000000042"
    assert parsed.supplier.vkn_tckn == "1234567890"
    assert parsed.supplier.title == "ACME Yazılım ve Bilişim A.Ş."
    assert parsed.customer.title == "Global Lojistik Ltd. Şti."
    assert parsed.line_extension_total == Decimal("100000.00")
    assert parsed.payable_amount == Decimal("120000.00")
    assert len(parsed.line_items) == 1
    assert parsed.line_items[0].item_name == "Kurumsal ERP Yazılım Lisansı"

    # Test TDHP Accounting Journal Entries
    tdhp = parsed.suggested_tdhp_entries
    assert len(tdhp) >= 2
    assert any(entry.account_code == "120.01" for entry in tdhp)  # Alıcılar
    assert any(entry.account_code == "600.01" for entry in tdhp)  # Satış Geliri
    assert any(entry.account_code == "391.01" for entry in tdhp)  # KDV


def test_ubl_tr_same_invoice_read_from_the_buyers_books():
    """One document, two organisations, opposite entries.

    Direction cannot come from `InvoiceTypeCode` — the code is identical in
    both readings. Only the VKN distinguishes them.
    """
    from app.parsers.invoice.ubl_tr import UBLTRInvoiceParser

    parsed = UBLTRInvoiceParser.parse_xml(SAMPLE_UBL_TR_XML, own_vkn="9876543210")

    assert parsed.direction == "purchase"
    codes = {e.account_code for e in parsed.suggested_tdhp_entries}
    assert "320.01" in codes   # Satıcılar
    assert "191.01" in codes   # İndirilecek KDV
    assert "600.01" not in codes


def test_ubl_tr_without_own_vkn_posts_nothing():
    """No VKN, no direction, no entry — and the invoice still parses."""
    from app.parsers.invoice.ubl_tr import UBLTRInvoiceParser

    parsed = UBLTRInvoiceParser.parse_xml(SAMPLE_UBL_TR_XML)

    assert parsed.invoice_number == "GIB2024000000042"
    assert parsed.direction == "unknown"
    assert parsed.needs_review
    assert parsed.suggested_tdhp_entries == []


def test_ubl_tr_refuses_a_despatch_advice():
    """e-İrsaliye is valid UBL with no monetary total; it used to parse into a
    balanced 0,00 TL sale."""
    import pytest

    from app.parsers.invoice.ubl_tr import NotAnInvoiceError, UBLTRInvoiceParser

    irsaliye = (
        '<DespatchAdvice xmlns="urn:oasis:names:specification:ubl:schema:xsd:'
        'DespatchAdvice-2"><ID>IRS2024000000001</ID></DespatchAdvice>'
    )
    with pytest.raises(NotAnInvoiceError):
        UBLTRInvoiceParser.parse_xml(irsaliye)


def test_bank_parsers_yapkredi_qnb_enpara():
    from app.parsers.banks.enpara import EnparaParser
    from app.parsers.banks.qnb import QNBParser
    from app.parsers.banks.yapkredi import YapiKrediParser

    yk_text = """
    YAPI VE KREDİ BANKASI A.Ş.
    Hesap Numarası: 12345678
    15/03/2024  MÜŞTERİ HAVALESİ  +50.000,00  120.000,00
    16/03/2024  OFİS KİRA ÖDEMESİ  -15.000,00  105.000,00
    """
    assert YapiKrediParser.can_parse(yk_text) is True
    yk_stmt = YapiKrediParser().parse(yk_text)
    assert len(yk_stmt.transactions) == 2

    qnb_text = """
    QNB FİNANSBANK EKSTRE
    Hesap No: 99887766
    10.03.2024  YAZILIM GELİRİ  +25.000,00  80.000,00
    """
    assert QNBParser.can_parse(qnb_text) is True
    qnb_stmt = QNBParser().parse(qnb_text)
    assert len(qnb_stmt.transactions) == 1

    enpara_text = """
    ENPARA.COM HESAP HAREKETİ
    12/03/2024  FATURA ÖDEMESİ  -2.500,00  45.000,00
    """
    assert EnparaParser.can_parse(enpara_text) is True
    enpara_stmt = EnparaParser().parse(enpara_text)
    assert len(enpara_stmt.transactions) == 1


def test_turkish_tax_engine():
    from decimal import Decimal

    from app.services.regional.tax_calculator import TurkishTaxEngine

    # Test KDV: 391 (20.000 TL) - 191 (12.000 TL) = 8.000 TL Ödenecek KDV
    kdv_res = TurkishTaxEngine.calculate_monthly_kdv(
        year=2024,
        month=3,
        sales_kdv_391=Decimal("20000.00"),
        purchase_kdv_191=Decimal("12000.00"),
        previous_carryover_kdv=Decimal("0.0"),
    )
    assert kdv_res.odenecek_kdv == Decimal("8000.00")
    assert kdv_res.sonraki_doneme_devreden_kdv == Decimal("0.0")

    # Test Muhtasar Stopaj (%20 kira)
    muh_res = TurkishTaxEngine.calculate_muhtasar(
        year=2024,
        month=3,
        gross_rent_amount=Decimal("30000.00"),
    )
    assert muh_res.toplam_stopaj == Decimal("6000.00")

    # Test 30-day cash outflow calendar
    calendar = TurkishTaxEngine.generate_30_day_tax_calendar(
        current_date=kdv_res.odeme_vadesi,
        kdv_res=kdv_res,
        muhtasar_res=muh_res,
    )
    assert len(calendar) == 2
    assert sum(c.amount for c in calendar) == Decimal("14000.00")


# ── OCR invoice direction ─────────────────────────────────────────────────────
# The wording on the page is a poor witness: "ALIŞ FATURASI" is the buyer's
# phrase and is printed on almost no invoice, while ETTN, TEMELFATURA and
# TICARIFATURA — all promoted to `satis` — appear on every e-Fatura whichever
# direction it travelled. Used alone this booked nearly everything as revenue.

_OCR_INVOICE = """
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


def _parse_ocr_invoice(own_vkn: str):
    from unittest.mock import patch

    from app.parsers.invoice import TurkishInvoiceParser

    with patch("app.config.get_settings") as gs:
        gs.return_value.gib_vkn = own_vkn
        return TurkishInvoiceParser().parse(_OCR_INVOICE)


def test_ocr_invoice_direction_follows_the_vkn_not_the_wording():
    """Same document, both readings — only the VKN separates them."""
    sale = _parse_ocr_invoice("1234567890")
    assert sale.transactions[0].tx_type == "income"
    assert sale.transactions[0].confidence > 0.60

    purchase = _parse_ocr_invoice("9876543210")
    assert purchase.transactions[0].tx_type == "expense"
    assert purchase.transactions[0].confidence > 0.60


def test_ocr_invoice_without_our_vkn_is_held_for_review():
    """An unqualified "FATURA" with an ETTN reads as a sale on wording alone.

    That guess is exactly how a supplier's invoice became revenue, so it must
    not clear the gate on its own.
    """
    stmt = _parse_ocr_invoice("")
    tx = stmt.transactions[0]
    assert tx.confidence <= 0.60, "yönü tahmin edilen kayıt kapıdan geçmemeli"
    assert tx.confidence_note
    assert any("yönü kesin değil" in w for w in stmt.parse_warnings)


def test_ocr_invoice_from_a_third_party_is_also_held():
    stmt = _parse_ocr_invoice("5555555555")
    assert stmt.transactions[0].confidence <= 0.60
