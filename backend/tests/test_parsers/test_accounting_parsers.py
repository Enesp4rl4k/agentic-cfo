"""
Tests for accounting parsers: Logo Tiger, Paraşüt.
Uses synthetic CSV fixtures — no real files needed.
"""
import pytest
from app.parsers.accounting.logo_tiger import LogoTigerParser
from app.parsers.accounting.parasut import ParasutParser


# ── Logo Tiger fixtures ───────────────────────────────────────────────────────

LOGO_TIGER_CSV = """LOGO YAZILIM A.Ş.
Şirket: Test Şirketi
Fiş Listesi Raporu
Hesap Hareketleri

Tarih;Fiş No;Açıklama;Borç;Alacak;Bakiye
15.01.2024;F001;Elektrik Faturası;2500,00;;47500,00
20.01.2024;G001;Müşteri Ödemesi;;15000,00;62500,00
25.01.2024;F002;Kira Ödemesi;8000,00;;54500,00
31.01.2024;F003;Maaş Ödemesi;25000,00;;29500,00
"""

LOGO_TIGER_MIZAN = """LOGO Tiger Muhasebe - Mizan Raporu
Hesap Kodu;Hesap Adı;Borç;Alacak;Borç Bakiye;Alacak Bakiye
600;Yurt İçi Satışlar;;120000,00;;120000,00
660;Araştırma Giderleri;5000,00;;5000,00;
741;Pazarlama Giderleri;8000,00;;8000,00;
"""


# ── Paraşüt fixtures ──────────────────────────────────────────────────────────

PARASUT_TRANSACTION_CSV = """Paraşüt - İşlem Raporu
Tarih,Tip,Kategori,Açıklama,Tutar,Döviz,Hesap
2024-01-15,Gelir,Satış,Müşteri Ödemesi,5000.00,TRY,Ana Hesap
2024-01-18,Gider,Kira,Ofis Kirası,2500.00,TRY,Ana Hesap
2024-01-20,Satış Faturası,Satış,Fatura #1001,8000.00,TRY,Ana Hesap
2024-01-22,Alış Faturası,Tedarikçi,Hammadde Alımı,3000.00,TRY,Ana Hesap
2024-01-25,Kasa Girişi,Tahsilat,Nakit Tahsilat,1200.00,TRY,Kasa
2024-01-28,Kasa Çıkışı,Gider,Kasa Ödemesi,500.00,TRY,Kasa
"""

PARASUT_INVOICE_CSV = """Paraşüt Fatura Listesi
Tarih,Fatura No,Müşteri/Tedarikçi,Açıklama,Tutar,KDV,Toplam,Durum
2024-01-10,INV-001,ABC Ltd,Hizmet Bedeli,10000.00,2000.00,12000.00,Ödendi
2024-01-15,INV-002,XYZ A.Ş.,Ürün Satışı,5000.00,1000.00,6000.00,Bekliyor
"""


# ── LogoTigerParser — Detection ───────────────────────────────────────────────

class TestLogoTigerDetection:

    def test_detects_logo_marker(self):
        assert LogoTigerParser.can_parse("LOGO YAZILIM raporları") is True

    def test_detects_tiger_muhasebe(self):
        assert LogoTigerParser.can_parse("Tiger Muhasebe export") is True

    def test_detects_fis_listesi(self):
        assert LogoTigerParser.can_parse("Fiş Listesi raporu") is True

    def test_detects_hesap_hareketleri(self):
        assert LogoTigerParser.can_parse("Hesap Hareketleri dökümü") is True

    def test_detects_borcalacak_headers(self):
        assert LogoTigerParser.can_parse("BORÇ;ALACAK;BAKİYE") is True

    def test_does_not_detect_garanti(self):
        garanti_text = "GARANTİ BBVA Hesap Ekstresi\n10.02.2024  Ödeme  +1000,00"
        assert LogoTigerParser.can_parse(garanti_text) is False

    def test_does_not_detect_empty(self):
        assert LogoTigerParser.can_parse("") is False


# ── LogoTigerParser — Parsing ─────────────────────────────────────────────────

class TestLogoTigerParsing:

    def setup_method(self):
        self.parser = LogoTigerParser()
        self.result = self.parser.parse(LOGO_TIGER_CSV)

    def test_returns_parsed_statement(self):
        from app.parsers.base import ParsedStatement
        assert isinstance(self.result, ParsedStatement)

    def test_has_transactions(self):
        assert len(self.result.transactions) > 0

    def test_expense_transaction_parsed(self):
        """Borç (debit) entries should be expenses."""
        expenses = [t for t in self.result.transactions if t.tx_type == "expense"]
        assert len(expenses) > 0

    def test_income_transaction_parsed(self):
        """Alacak (credit) entries should be income."""
        incomes = [t for t in self.result.transactions if t.tx_type == "income"]
        assert len(incomes) > 0

    def test_amount_positive(self):
        """All amounts should be positive."""
        for tx in self.result.transactions:
            assert tx.amount_cents > 0

    def test_date_parsed(self):
        """Transactions should have dates (field is 'date', not 'transaction_date')."""
        for tx in self.result.transactions:
            if tx.date:
                assert tx.date.year == 2024

    def test_description_populated(self):
        """Descriptions should not be empty."""
        for tx in self.result.transactions:
            assert tx.description

    def test_bank_name_is_logo_tiger(self):
        assert "logo" in self.result.bank_name.lower() or "tiger" in self.result.bank_name.lower()


# ── ParasutParser — Detection ─────────────────────────────────────────────────

class TestParasutDetection:

    def test_detects_parasut_header(self):
        assert ParasutParser.can_parse("Paraşüt - İşlem Raporu") is True

    def test_detects_parasut_com(self):
        assert ParasutParser.can_parse("app.parasut.com export") is True

    def test_detects_islem_tarihi(self):
        assert ParasutParser.can_parse("İşlem Tarihi,Tip,Kategori") is True

    def test_does_not_detect_akbank(self):
        akbank_text = "AKBANK T.A.Ş. Hesap Ekstresi\n15.01.2024  Ödeme  250,00"
        assert ParasutParser.can_parse(akbank_text) is False

    def test_does_not_detect_empty(self):
        assert ParasutParser.can_parse("") is False


# ── ParasutParser — Parsing ───────────────────────────────────────────────────

class TestParasutParsing:

    def setup_method(self):
        self.parser = ParasutParser()
        self.result = self.parser.parse(PARASUT_TRANSACTION_CSV)

    def test_returns_parsed_statement(self):
        from app.parsers.base import ParsedStatement
        assert isinstance(self.result, ParsedStatement)

    def test_has_transactions(self):
        assert len(self.result.transactions) > 0

    def test_gelir_is_income(self):
        incomes = [t for t in self.result.transactions if t.tx_type == "income"]
        assert len(incomes) > 0

    def test_gider_is_expense(self):
        expenses = [t for t in self.result.transactions if t.tx_type == "expense"]
        assert len(expenses) > 0

    def test_satis_faturasi_is_income(self):
        """Satış Faturası → income."""
        incomes = [t for t in self.result.transactions if t.tx_type == "income"]
        # Should have at least the "Gelir" and "Satış Faturası" entries
        assert len(incomes) >= 2

    def test_alis_faturasi_is_expense(self):
        """Alış Faturası → expense."""
        expenses = [t for t in self.result.transactions if t.tx_type == "expense"]
        assert len(expenses) >= 2

    def test_kasa_girisi_is_income(self):
        """Kasa Girişi → income."""
        incomes = [t for t in self.result.transactions if t.tx_type == "income"]
        assert len(incomes) >= 3

    def test_kasa_cikisi_is_expense(self):
        """Kasa Çıkışı → expense."""
        expenses = [t for t in self.result.transactions if t.tx_type == "expense"]
        assert len(expenses) >= 3

    def test_amount_positive(self):
        for tx in self.result.transactions:
            assert tx.amount_cents > 0, f"Amount should be positive: {tx}"

    def test_currency_is_try(self):
        for tx in self.result.transactions:
            if tx.currency:
                assert tx.currency == "TRY"

    def test_bank_name_is_parasut(self):
        assert "para" in self.result.bank_name.lower() or "parasut" in self.result.bank_name.lower()


# ── ParserRegistry integration ────────────────────────────────────────────────

class TestParserRegistryAccounting:

    def test_logo_tiger_registered(self):
        """Registry.detect() returns a class, check with issubclass."""
        from app.parsers.registry import ParserRegistry
        parser_cls = ParserRegistry.detect(LOGO_TIGER_CSV)
        assert parser_cls is not None
        # detect() returns the class itself, not an instance
        assert parser_cls is LogoTigerParser or (
            isinstance(parser_cls, LogoTigerParser)
        )

    def test_parasut_can_parse_its_own_fixture(self):
        """Paraşüt CSV contains 'Paraşüt' marker — direct can_parse check."""
        assert ParasutParser.can_parse(PARASUT_TRANSACTION_CSV) is True

    def test_parasut_does_not_match_logo_csv(self):
        assert ParasutParser.can_parse(LOGO_TIGER_CSV) is False

    def test_logo_tiger_does_not_match_parasut_csv(self):
        assert LogoTigerParser.can_parse(PARASUT_TRANSACTION_CSV) is False
