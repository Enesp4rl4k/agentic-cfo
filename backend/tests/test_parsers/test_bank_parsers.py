"""
Tests for bank statement parsers.
Uses synthetic text fixtures — no real PDF files needed.
done_when: pytest tests/test_parsers/ -q → all pass
"""

from app.parsers.banks.akbank import AkbankParser
from app.parsers.banks.garanti import GarantiParser
from app.parsers.banks.isbank import IsBankParser
from app.parsers.banks.ziraat import ZiraatParser
from app.parsers.registry import ParserRegistry
from app.parsers.base import BankParser

# ── Fixtures — synthetic statement text ──────────────────────────────────────

AKBANK_TEXT = """
AKBANK T.A.Ş. Hesap Ekstresi
Hesap No: 1234-5678-9012

15.01.2024  ELEKTRİK FATURASI          250,00              5.750,00
20.01.2024  MÜŞTERİ ÖDEMESİ                    1.500,00    7.250,00
25.01.2024  KİRA ÖDEMESİ               3.500,00            3.750,00
"""

GARANTI_TEXT = """
GARANTİ BBVA Hesap Ekstresi
Hesap No: 9876-5432

10.02.2024  15.02.2024  FATURA TAHSİLATI    +2.000,00   12.000,00
12.02.2024  12.02.2024  MAAŞ ÖDEMESİ        -4.500,00    7.500,00
"""

ISBANK_TEXT = """
TÜRKİYE İŞ BANKASI
Hesap Numarası: 4567-8901-2345

05.03.2024  YAZILIM LİSANSI    500,00    -       8.500,00
10.03.2024  SATIŞ GELİRİ       -         3.000,00  11.500,00
"""

ZIRAAT_TEXT = """
T.C. ZİRAAT BANKASI Hesap Ekstresi
Hesap No: 7890-1234

01.04.2024  PAZARLAMA GİDERİ   1.200,00   -        9.800,00
15.04.2024  TAHSİLAT           -          5.000,00  14.800,00
"""

# ── Detection tests ───────────────────────────────────────────────────────────

def test_detect_akbank():
    assert AkbankParser.can_parse(AKBANK_TEXT) is True

def test_detect_garanti():
    assert GarantiParser.can_parse(GARANTI_TEXT) is True

def test_detect_isbank():
    assert IsBankParser.can_parse(ISBANK_TEXT) is True

def test_detect_ziraat():
    assert ZiraatParser.can_parse(ZIRAAT_TEXT) is True

def test_no_cross_detection():
    """Garanti parser should not match Akbank text."""
    # Both have generic "Hesap No" but bank name check should differentiate
    assert GarantiParser.can_parse(AKBANK_TEXT) is False

# ── Amount parsing tests ──────────────────────────────────────────────────────

def test_parse_amount_turkish_format():
    assert BankParser.parse_turkish_amount("1.234,56") == 123456

def test_parse_amount_simple():
    assert BankParser.parse_turkish_amount("500,00") == 50000

def test_parse_amount_with_symbol():
    assert BankParser.parse_turkish_amount("₺1.500,00") == 150000

def test_parse_amount_invalid():
    assert BankParser.parse_turkish_amount("N/A") is None

def test_parse_amount_integer():
    assert BankParser.parse_turkish_amount("3.500") == 350000

# ── Date parsing tests ────────────────────────────────────────────────────────

def test_parse_date_dot_format():
    d = BankParser.parse_turkish_date("15.01.2024")
    assert d is not None
    assert d.day == 15
    assert d.month == 1
    assert d.year == 2024

def test_parse_date_iso_format():
    d = BankParser.parse_turkish_date("2024-03-20")
    assert d is not None
    assert d.month == 3

def test_parse_date_invalid():
    assert BankParser.parse_turkish_date("not-a-date") is None

# ── Registry tests ────────────────────────────────────────────────────────────

def test_registry_detects_akbank():
    from app.parsers.registry import ParserRegistry
    cls = ParserRegistry.detect(AKBANK_TEXT)
    assert cls is not None
    assert cls.bank_id == "akbank"

def test_registry_detects_garanti():
    cls = ParserRegistry.detect(GARANTI_TEXT)
    assert cls is not None
    assert cls.bank_id == "garanti"

def test_registry_falls_back_to_generic():
    cls = ParserRegistry.detect("Some random text with no bank name")
    # Generic always matches, but structured parsers won't
    # detect() returns None if no structured parser matches
    # (Generic is handled separately in parse())
    assert cls is None or cls.bank_id == "generic"

# ── Classifier keyword tests ──────────────────────────────────────────────────

def test_classify_salary():
    from app.services.classifier import classify_by_keywords
    assert classify_by_keywords("Maaş Ödemesi Ocak") == "salary"

def test_classify_rent():
    from app.services.classifier import classify_by_keywords
    assert classify_by_keywords("Kira Faturası Şubat") == "rent"

def test_classify_utilities():
    from app.services.classifier import classify_by_keywords
    assert classify_by_keywords("Elektrik Faturası") == "utilities"

def test_classify_unknown():
    from app.services.classifier import classify_by_keywords
    assert classify_by_keywords("Bilinmeyen işlem xyz") == "other_expense"
