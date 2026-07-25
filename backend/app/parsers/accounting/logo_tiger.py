"""
Logo Tiger parser — Türkiye'nin en yaygın muhasebe yazılımı.

Logo Tiger CSV/Excel export formatları:
  - Fiş raporu: Tarih;Fiş No;Açıklama;Borç;Alacak;Bakiye
  - Hesap ekstresi: Tarih;Belge Türü;Belge No;Hesap Kodu;Açıklama;Borç;Alacak
  - Mizan raporu: Hesap Kodu;Hesap Adı;Borç;Alacak;Borç Bakiye;Alacak Bakiye

Logo Tiger başlık satırında tipik olarak "LOGO" veya "Tiger" veya
"Fiş Listesi" / "Hesap Hareketleri" gibi ifadeler içerir.

Muhasebe mantığı:
  - Borç (debit) = gider (expense) — şirket para öder
  - Alacak (credit) = gelir (income) — şirket para alır
  - Bazı hesaplarda bu tersine dönebilir; 6xx hesaplar gider, 7xx gelir

Desteklenen hesap kodları:
  6xx → Gider hesapları (expense)
  7xx → Gelir hesapları (income)
  1xx → Dönen varlıklar (asset — skip veya cashflow)
  3xx → Kısa vadeli yükümlülükler (liability — skip)
"""
from __future__ import annotations

import csv
import io
import re
from datetime import datetime, timezone
from typing import Any

from app.parsers.base import BankParser, ParsedStatement, ParsedTransaction


class LogoTigerParser(BankParser):
    bank_id = "logo_tiger"
    bank_display_name = "Logo Tiger"

    _MARKERS = [
        "LOGO", "Logo Tiger", "Tiger Muhasebe", "Fiş Listesi",
        "Hesap Hareketleri", "LOGO YAZILIM", "LG YAZILIM",
        "Mizan", "Fis No", "Fiş No", "BORÇ", "ALACAK",
    ]

    # Flexible column name variants
    _DATE_COLS    = ["tarih", "date", "işlem tarihi", "islem tarihi", "belge tarihi"]
    _DEBIT_COLS   = ["borç", "bor", "borç tutarı", "debit", "tutar (borç)"]
    _CREDIT_COLS  = ["alacak", "alacak tutarı", "credit", "tutar (alacak)"]
    _DESC_COLS    = ["açıklama", "aciklama", "description", "hareket açıklaması", "fiş açıklaması"]
    _REF_COLS     = ["fiş no", "fis no", "belge no", "referans", "evrak no"]
    _ACCOUNT_COLS = ["hesap kodu", "hesap", "account code"]

    @classmethod
    def can_parse(cls, text: str) -> bool:
        text_upper = text.upper()
        return any(m.upper() in text_upper for m in cls._MARKERS)

    def parse(self, text: str, file_path: str = "") -> ParsedStatement:
        statement = ParsedStatement(
            bank_name=self.bank_display_name,
            account_number=self._extract_account(text),
            statement_period_start=None,
            statement_period_end=None,
        )

        # Try CSV parse first
        transactions = self._parse_csv(text)
        if not transactions:
            # Fallback: line-based parsing for non-standard formats
            transactions = self._parse_line_based(text)

        statement.transactions = transactions

        if not transactions:
            statement.parse_warnings.append(
                "Logo Tiger: İşlem bulunamadı. CSV formatını kontrol edin."
            )

        # Set period from transactions
        if transactions:
            dates = [t.date for t in transactions]
            statement.statement_period_start = min(dates)
            statement.statement_period_end   = max(dates)

        return statement

    def _extract_account(self, text: str) -> str | None:
        m = re.search(r"(?:Hesap|HESAP)\s*(?:Kodu|No|Numarası)[:\s]*([A-Z0-9./\-]{3,20})", text, re.IGNORECASE)
        return m.group(1).strip() if m else None

    def _find_col(self, headers: list[str], candidates: list[str]) -> int | None:
        """Find column index matching any candidate name (case-insensitive)."""
        headers_lower = [h.strip().lower() for h in headers]
        for cand in candidates:
            cand_lower = cand.lower()
            for i, h in enumerate(headers_lower):
                if cand_lower in h or h in cand_lower:
                    return i
        return None

    def _parse_csv(self, text: str) -> list[ParsedTransaction]:
        """Parse standard Logo Tiger CSV export."""
        transactions: list[ParsedTransaction] = []

        # Detect delimiter: Logo uses ";" by default
        delimiter = ";" if text.count(";") > text.count(",") else ","

        try:
            reader = csv.reader(io.StringIO(text), delimiter=delimiter)
            rows = list(reader)
        except Exception:
            return []

        if not rows:
            return []

        # Find header row (contains date/debit/credit markers)
        header_row_idx = 0
        for i, row in enumerate(rows[:10]):
            row_joined = " ".join(row).lower()
            if any(c in row_joined for c in ["tarih", "borç", "alacak", "date", "debit"]):
                header_row_idx = i
                break

        headers = rows[header_row_idx]

        date_col    = self._find_col(headers, self._DATE_COLS)
        debit_col   = self._find_col(headers, self._DEBIT_COLS)
        credit_col  = self._find_col(headers, self._CREDIT_COLS)
        desc_col    = self._find_col(headers, self._DESC_COLS)
        ref_col     = self._find_col(headers, self._REF_COLS)
        account_col = self._find_col(headers, self._ACCOUNT_COLS)

        if date_col is None or (debit_col is None and credit_col is None):
            return []

        for row in rows[header_row_idx + 1:]:
            if len(row) <= max(c for c in [date_col, debit_col, credit_col] if c is not None):
                continue

            # Date
            raw_date = row[date_col].strip() if date_col < len(row) else ""
            date = self.parse_turkish_date(raw_date)
            if not date:
                continue

            # Description
            description = ""
            if desc_col is not None and desc_col < len(row):
                description = row[desc_col].strip()

            # Reference
            reference = None
            if ref_col is not None and ref_col < len(row):
                reference = row[ref_col].strip() or None

            # Determine transaction type from account code if available
            account_code = ""
            if account_col is not None and account_col < len(row):
                account_code = row[account_col].strip()

            # Debit amount (borç) → expense
            debit_cents = 0
            if debit_col is not None and debit_col < len(row):
                raw = row[debit_col].strip()
                if raw and raw not in ("0", "0,00", "0.00", "-"):
                    parsed = self.parse_turkish_amount(raw)
                    if parsed:
                        debit_cents = parsed

            # Credit amount (alacak) → income
            credit_cents = 0
            if credit_col is not None and credit_col < len(row):
                raw = row[credit_col].strip()
                if raw and raw not in ("0", "0,00", "0.00", "-"):
                    parsed = self.parse_turkish_amount(raw)
                    if parsed:
                        credit_cents = parsed

            # Determine tx type from amounts and account code
            tx_type, amount = self._resolve_tx_type(
                debit_cents, credit_cents, account_code
            )

            if amount <= 0:
                continue

            transactions.append(ParsedTransaction(
                date=date,
                description=description or f"Logo işlemi {date.strftime('%d.%m.%Y')}",
                amount_cents=amount,
                tx_type=tx_type,
                currency="TRY",
                vendor=self._extract_vendor(description),
                reference=reference,
                raw_row=delimiter.join(row),
            ))

        return transactions

    def _parse_line_based(self, text: str) -> list[ParsedTransaction]:
        """
        Fallback parser for non-CSV Logo exports (e.g. copy-pasted text).
        Looks for lines with date + amount pattern.
        """
        transactions: list[ParsedTransaction] = []
        date_amount_pattern = re.compile(
            r"(\d{2}[./]\d{2}[./]\d{4})"       # date
            r".*?"
            r"([\d.,]+)\s*"                      # debit amount
            r"([\d.,]*)\s*"                      # credit amount (optional)
            r"([\d.,]*)"                         # balance (optional)
        )
        for line in text.splitlines():
            m = date_amount_pattern.search(line)
            if not m:
                continue
            date = self.parse_turkish_date(m.group(1))
            if not date:
                continue
            debit  = self.parse_turkish_amount(m.group(2)) or 0
            credit = self.parse_turkish_amount(m.group(3)) or 0
            tx_type, amount = self._resolve_tx_type(debit, credit, "")
            if amount <= 0:
                continue
            desc = line[:80].strip()
            transactions.append(ParsedTransaction(
                date=date,
                description=desc,
                amount_cents=amount,
                tx_type=tx_type,
                currency="TRY",
                raw_row=line,
            ))
        return transactions

    @staticmethod
    def _resolve_tx_type(
        debit: int, credit: int, account_code: str
    ) -> tuple[str, int]:
        """
        Determine transaction type and canonical amount.

        Logo Tiger accounting logic:
        - 6xx accounts (expense): debit = expense, credit = reversal/income
        - 7xx accounts (income/revenue): credit = income, debit = reversal
        - If no account code: credit > 0 → income, debit > 0 → expense
        """
        acc_prefix = account_code[:1] if account_code else ""

        if acc_prefix == "6":
            # Cost/expense account
            if debit > 0:
                return "expense", debit
            elif credit > 0:
                return "income", credit  # reversal treated as income
        elif acc_prefix == "7":
            # Revenue account
            if credit > 0:
                return "income", credit
            elif debit > 0:
                return "expense", debit  # reversal
        else:
            # Generic: credit = income, debit = expense
            if credit > 0 and debit == 0:
                return "income", credit
            elif debit > 0 and credit == 0:
                return "expense", debit
            elif credit > 0 and debit > 0:
                # Net position
                net = credit - debit
                if net > 0:
                    return "income", net
                else:
                    return "expense", abs(net)

        return "expense", 0

    @staticmethod
    def _extract_vendor(description: str) -> str | None:
        """Extract vendor name from Logo Tiger description field."""
        if not description:
            return None
        # Logo often formats: "VENDOR_NAME - AÇIKLAMA" or "AÇIKLAMA / VENDOR"
        parts = re.split(r"\s[-/]\s", description, maxsplit=1)
        if len(parts) > 1:
            return parts[0].strip()[:100]
        # Just return first 50 chars as vendor hint
        return description[:50].strip() if len(description) > 10 else None
