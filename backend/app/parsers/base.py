"""
Bank statement parser — base types and parsed data models.

Each bank parser produces a list of ParsedTransaction objects.
The LLM is only used as a fallback (GenericParser) when no bank-specific
parser matches. Structured parsers are faster and more reliable.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import ClassVar


@dataclass
class ParsedTransaction:
    """Normalised transaction extracted from a bank statement."""
    date: datetime
    description: str
    amount_cents: int          # Always positive; sign determined by tx_type
    tx_type: str               # "income" | "expense"
    currency: str = "TRY"
    vendor: str | None = None
    balance_cents: int | None = None   # Running balance if available
    reference: str | None = None       # Bank reference / cheque number
    raw_row: str = ""                  # Original text row for audit


@dataclass
class ParsedStatement:
    """Full parsed bank statement."""
    bank_name: str
    account_number: str | None
    statement_period_start: datetime | None
    statement_period_end: datetime | None
    transactions: list[ParsedTransaction] = field(default_factory=list)
    parse_warnings: list[str] = field(default_factory=list)

    @property
    def transaction_count(self) -> int:
        return len(self.transactions)

    @property
    def total_income_cents(self) -> int:
        return sum(t.amount_cents for t in self.transactions if t.tx_type == "income")

    @property
    def total_expense_cents(self) -> int:
        return sum(t.amount_cents for t in self.transactions if t.tx_type == "expense")


class BankParser(ABC):
    """Abstract base class for all bank statement parsers."""

    # Subclasses set this to identify themselves in the registry
    bank_id: ClassVar[str] = ""
    bank_display_name: ClassVar[str] = ""

    @classmethod
    @abstractmethod
    def can_parse(cls, text: str) -> bool:
        """
        Quick heuristic check — does this text look like a statement
        from this bank? Called before attempting a full parse.
        """

    @abstractmethod
    def parse(self, text: str, file_path: str) -> ParsedStatement:
        """
        Parse the full statement text and return a ParsedStatement.
        Implementations should never raise — capture issues in
        ParsedStatement.parse_warnings instead.
        """

    # ── Shared utilities ───────────────────────────────────────────────────

    @staticmethod
    def parse_turkish_amount(raw: str) -> int | None:
        """
        Convert Turkish-formatted amount string to cents.

        Handles:
          "1.234,56"  → 123456   (Turkish: dot=thousands, comma=decimal)
          "1.234"     → 350000   wait, "3.500" → 3500 TL → 350000 kuruş
          "500,00"    → 50000
          "1234.56"   → 123456   (US format fallback)
        """
        import re
        cleaned = raw.strip().replace(" ", "").replace("\xa0", "")
        # Remove currency symbols
        cleaned = re.sub(r"[TL₺$€£+]", "", cleaned)
        cleaned = cleaned.strip().lstrip("-")
        if not cleaned:
            return None

        # Turkish format: both dot and comma present → "1.234,56"
        if "," in cleaned and "." in cleaned:
            # dot = thousands separator, comma = decimal
            cleaned = cleaned.replace(".", "").replace(",", ".")
        elif "," in cleaned:
            # only comma → decimal separator "500,00"
            cleaned = cleaned.replace(",", ".")
        elif "." in cleaned:
            # only dot: could be thousands separator ("3.500") or decimal ("3.5")
            # Rule: if exactly 3 digits after dot → thousands separator
            parts = cleaned.split(".")
            if len(parts) == 2 and len(parts[1]) == 3:
                # "3.500" → 3500 (thousands separator, no decimal)
                cleaned = cleaned.replace(".", "")
            # else: "3.5" → decimal, leave as-is

        try:
            return round(float(cleaned) * 100)
        except ValueError:
            return None

    @staticmethod
    def parse_turkish_date(raw: str) -> datetime | None:
        """
        Try common Turkish date formats.

        Handles:
          "15.03.2024"  — standard Turkish
          "15/03/2024"  — slash separator
          "2024-03-15"  — ISO
          "15.03.24"    — 2-digit year
          "15 Mart 2024" — Turkish month name
          "15-Mart-2024" — hyphen with month name
        """
        from datetime import timezone

        raw = raw.strip()

        # Standard numeric formats
        numeric_formats = [
            "%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d",
            "%d.%m.%y", "%d-%m-%Y", "%d %m %Y",
            "%d/%m/%y", "%Y/%m/%d",
        ]
        for fmt in numeric_formats:
            try:
                return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue

        # Turkish month names → number mapping
        _TR_MONTHS = {
            "ocak": 1, "şubat": 2, "mart": 3, "nisan": 4,
            "mayıs": 5, "haziran": 6, "temmuz": 7, "ağustos": 8,
            "eylül": 9, "ekim": 10, "kasım": 11, "aralık": 12,
            # Common abbreviations
            "oca": 1, "şub": 2, "mar": 3, "nis": 4,
            "may": 5, "haz": 6, "tem": 7, "ağu": 8,
            "eyl": 9, "eki": 10, "kas": 11, "ara": 12,
        }
        import re as _re
        # "15 Mart 2024" or "15-Mart-2024" or "15.Mart.2024"
        m = _re.match(r"(\d{1,2})[\s.\-/]([A-Za-zğüşıöçĞÜŞİÖÇ]+)[\s.\-/](\d{2,4})", raw)
        if m:
            day, month_str, year_str = int(m.group(1)), m.group(2).lower(), m.group(3)
            month_num = _TR_MONTHS.get(month_str)
            if month_num:
                year = int(year_str)
                if year < 100:
                    year += 2000
                try:
                    return datetime(year, month_num, day, tzinfo=timezone.utc)
                except ValueError:
                    pass

        return None
