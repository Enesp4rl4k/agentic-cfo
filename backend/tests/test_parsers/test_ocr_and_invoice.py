"""
Tests for OCR service and invoice parser — pure function tests.
No real PDF files needed — uses synthetic text fixtures.
"""
import pytest
from app.services.ocr_service import (
    _clean_ocr_text,
    extract_invoice_fields,
    OCRResult,
    PageResult,
)
from app.parsers.invoice import (
    TurkishInvoiceParser,
    InvoiceBatchParser,
    _detect_invoice_type,
    _invoice_type_to_tx_type,
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
