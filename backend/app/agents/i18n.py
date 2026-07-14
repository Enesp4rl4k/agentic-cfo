"""
Language support for CFO agent narratives.

Supported languages:
  - tr: Türkçe (default)
  - en: English
  - de: Deutsch

Usage:
    from app.agents.i18n import get_language_instruction, LANG_NAMES

    system_suffix = get_language_instruction("de")
    # → "Respond in German (Deutsch)."
"""
from __future__ import annotations

SUPPORTED_LANGUAGES = ("tr", "en", "de")
DEFAULT_LANGUAGE = "tr"

LANG_NAMES = {
    "tr": "Türkçe",
    "en": "English",
    "de": "Deutsch",
}

LANG_INSTRUCTIONS = {
    "tr": "Yanıtını Türkçe olarak ver.",
    "en": "Respond in English.",
    "de": "Antworte auf Deutsch.",
}

# Label translations used in Excel reports and frontend
LABELS: dict[str, dict[str, str]] = {
    # P&L
    "revenue":              {"tr": "Gelir", "en": "Revenue", "de": "Umsatz"},
    "cogs":                 {"tr": "Satılan Mal Maliyeti", "en": "Cost of Goods Sold", "de": "Herstellungskosten"},
    "gross_profit":         {"tr": "Brüt Kâr", "en": "Gross Profit", "de": "Bruttogewinn"},
    "gross_margin":         {"tr": "Brüt Marj", "en": "Gross Margin", "de": "Bruttomarge"},
    "ebitda":               {"tr": "FAVÖK", "en": "EBITDA", "de": "EBITDA"},
    "ebitda_margin":        {"tr": "FAVÖK Marjı", "en": "EBITDA Margin", "de": "EBITDA-Marge"},
    "net_income":           {"tr": "Net Kâr", "en": "Net Income", "de": "Jahresüberschuss"},
    "net_margin":           {"tr": "Net Marj", "en": "Net Margin", "de": "Nettomarge"},
    "total_opex":           {"tr": "Toplam Faaliyet Gideri", "en": "Total OpEx", "de": "Betriebskosten gesamt"},
    # Cash Flow
    "operating":            {"tr": "Faaliyet Nakit Akışı", "en": "Operating Cash Flow", "de": "Betrieblicher Cashflow"},
    "investing":            {"tr": "Yatırım Nakit Akışı", "en": "Investing Cash Flow", "de": "Investitions-Cashflow"},
    "financing":            {"tr": "Finansman Nakit Akışı", "en": "Financing Cash Flow", "de": "Finanzierungs-Cashflow"},
    "net_change":           {"tr": "Net Nakit Değişimi", "en": "Net Cash Change", "de": "Netto-Cashveränderung"},
    "burn_rate":            {"tr": "Aylık Nakit Tüketimi", "en": "Monthly Burn Rate", "de": "Monatliche Verbrennung"},
    "runway_months":        {"tr": "Nakit Süresi (Ay)", "en": "Cash Runway (Months)", "de": "Cash-Runway (Monate)"},
    "working_capital":      {"tr": "İşletme Sermayesi", "en": "Working Capital", "de": "Betriebskapital"},
    # Balance Sheet
    "total_assets":         {"tr": "Toplam Aktifler", "en": "Total Assets", "de": "Bilanzsumme"},
    "current_assets":       {"tr": "Dönen Varlıklar", "en": "Current Assets", "de": "Umlaufvermögen"},
    "non_current_assets":   {"tr": "Duran Varlıklar", "en": "Non-Current Assets", "de": "Anlagevermögen"},
    "total_liabilities":    {"tr": "Toplam Yükümlülükler", "en": "Total Liabilities", "de": "Verbindlichkeiten gesamt"},
    "current_liabilities":  {"tr": "Kısa Vadeli Yükümlülükler", "en": "Current Liabilities", "de": "Kurzfristige Verbindlichkeiten"},
    "total_equity":         {"tr": "Öz Sermaye", "en": "Total Equity", "de": "Eigenkapital"},
    "cash":                 {"tr": "Nakit", "en": "Cash & Equivalents", "de": "Kassenbestand"},
    "accounts_receivable":  {"tr": "Ticari Alacaklar", "en": "Accounts Receivable", "de": "Forderungen"},
    "inventory":            {"tr": "Stok", "en": "Inventory", "de": "Vorräte"},
    "ppe":                  {"tr": "Maddi Duran Varlıklar", "en": "PP&E", "de": "Sachanlagen"},
    "accounts_payable":     {"tr": "Ticari Borçlar", "en": "Accounts Payable", "de": "Verbindlichkeiten a.L.L."},
    "short_term_debt":      {"tr": "Kısa Vadeli Borç", "en": "Short-term Debt", "de": "Kurzfristige Schulden"},
    "retained_earnings":    {"tr": "Geçmiş Dönem Kârı", "en": "Retained Earnings", "de": "Gewinnrücklagen"},
    "paid_in_capital":      {"tr": "Ödenmiş Sermaye", "en": "Paid-in Capital", "de": "Einbezahltes Kapital"},
    # Ratios
    "current_ratio":        {"tr": "Cari Oran", "en": "Current Ratio", "de": "Liquiditätsgrad 3"},
    "quick_ratio":          {"tr": "Asit-Test Oranı", "en": "Quick Ratio", "de": "Liquiditätsgrad 2"},
    "cash_ratio":           {"tr": "Nakit Oranı", "en": "Cash Ratio", "de": "Liquiditätsgrad 1"},
    "roa":                  {"tr": "Aktif Kârlılığı", "en": "Return on Assets", "de": "Gesamtkapitalrendite"},
    "roe":                  {"tr": "Öz Kaynak Kârlılığı", "en": "Return on Equity", "de": "Eigenkapitalrendite"},
    "roce":                 {"tr": "Kullanılan Sermaye Getirisi", "en": "ROCE", "de": "ROCE"},
    "debt_to_equity":       {"tr": "Borç/Öz Kaynak", "en": "Debt-to-Equity", "de": "Verschuldungsgrad"},
    "debt_ratio":           {"tr": "Borç Oranı", "en": "Debt Ratio", "de": "Fremdkapitalquote"},
    "interest_coverage":    {"tr": "Faiz Karşılama Oranı", "en": "Interest Coverage", "de": "Zinsdeckungsgrad"},
    "asset_turnover":       {"tr": "Aktif Devir Hızı", "en": "Asset Turnover", "de": "Kapitalumschlag"},
    "dso":                  {"tr": "Ortalama Tahsilat Süresi", "en": "Days Sales Outstanding", "de": "Debitorenlaufzeit"},
    "dio":                  {"tr": "Ortalama Stok Süresi", "en": "Days Inventory Outstanding", "de": "Lagerdauer"},
    "dpo":                  {"tr": "Ortalama Ödeme Süresi", "en": "Days Payable Outstanding", "de": "Kreditorenlaufzeit"},
    "cash_conversion_cycle": {"tr": "Nakit Dönüşüm Döngüsü", "en": "Cash Conversion Cycle", "de": "Cash-Conversion-Zyklus"},
    # Tax
    "kdv":                  {"tr": "KDV", "en": "VAT", "de": "MwSt."},
    "stopaj":               {"tr": "Stopaj", "en": "Withholding Tax", "de": "Quellensteuer"},
    "kurumlar_vergisi":     {"tr": "Kurumlar Vergisi", "en": "Corporate Tax", "de": "Körperschaftsteuer"},
    "gecici_vergi":         {"tr": "Geçici Vergi", "en": "Provisional Tax", "de": "Vorauszahlung"},
    # General
    "narrative":            {"tr": "CFO Yorumu", "en": "CFO Commentary", "de": "CFO-Kommentar"},
    "good":                 {"tr": "İyi", "en": "Good", "de": "Gut"},
    "warning":              {"tr": "Uyarı", "en": "Warning", "de": "Warnung"},
    "critical":             {"tr": "Kritik", "en": "Critical", "de": "Kritisch"},
}


def get_language_instruction(lang: str) -> str:
    """Return the language instruction to append to any system prompt."""
    lang = lang if lang in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE
    return LANG_INSTRUCTIONS[lang]


def label(key: str, lang: str) -> str:
    """Return translated label for a key."""
    lang = lang if lang in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE
    return LABELS.get(key, {}).get(lang, key)


def validate_language(lang: str) -> str:
    """Normalise and validate language code."""
    lang = lang.lower().strip()
    return lang if lang in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE
