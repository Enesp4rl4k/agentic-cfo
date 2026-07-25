"""
Netsis parser — orta ölçekli KOBİ'lerde yaygın muhasebe yazılımı.

Netsis export formatları:
  - Hesap Hareketleri: Tarih | Evrak No | Açıklama | Borç | Alacak | Bakiye
  - Fiş Listesi: Tarih | Fiş Türü | No | Hesap | Açıklama | Borç | Alacak
  - Banka Ekstresi: Değer Tarihi | İşlem | Tutar | Bakiye

Netsis başlık/logo satırında "NETSİS" veya "Netsis" veya "UNITY"
(Netsis Unity adıyla da bilinir) ifadeleri içerir.

Muhasebe mantığı Logo ile aynıdır:
  Borç = expense, Alacak = income (6xx/7xx hesap kuralları)
"""
from __future__ import annotations

import csv
import io
import re
from datetime import datetime

from app.parsers.base import BankParser, ParsedStatement, ParsedTransaction


class NetsisParser(BankParser):
    bank_id = "netsis"
    bank_display_name = "Netsis"

    _MARKERS = [
        "NETSİS", "NETSIS", "Netsis Unity", "UNITY",
        "Netsis Entegre", "NETSİS ENTEGRE",
        # Common Netsis column headers
        "EVRAK NO", "Evrak No", "FİŞ TÜRÜ", "Fis Turu",
    ]

    _DATE_COLS    = ["tarih", "işlem tarihi", "değer tarihi", "evrak tarihi", "date"]
    _DEBIT_COLS   = ["borç", "bor", "debit", "borç tutarı", "tutar (b)"]
    _CREDIT_COLS  = ["alacak", "credit", "alacak tutarı", "tutar (a)"]
    _DESC_COLS    = ["açıklama", "aciklama", "işlem açıklaması", "fiş açıklaması", "description"]
    _REF_COLS     = ["evrak no", "fiş no", "belge no", "no", "referans"]
    _ACCOUNT_COLS = ["hesap kodu", "hesap no", "hesap", "account"]

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
        transactions = self._parse_csv(text)
        if not transactions:
            transactions = self._parse_fixed_width(text)

        statement.transactions = transactions
        if not transactions:
            statement.parse_warnings.append("Netsis: İşlem bulunamadı.")
        if transactions:
            dates = [t.date for t in transactions]
            statement.statement_period_start = min(dates)
            statement.statement_period_end   = max(dates)
        return statement

    def _extract_account(self, text: str) -> str | None:
        m = re.search(r"(?:Hesap|HESAP|Cari)\s*(?:Kodu|No)[:\s]*([A-Z0-9./\-]{3,20})", text, re.IGNORECASE)
        return m.group(1).strip() if m else None

    def _find_col(self, headers: list[str], candidates: list[str]) -> int | None:
        headers_lower = [h.strip().lower() for h in headers]
        for cand in candidates:
            cand_lower = cand.lower()
            for i, h in enumerate(headers_lower):
                if cand_lower in h or h in cand_lower:
                    return i
        return None

    def _parse_csv(self, text: str) -> list[ParsedTransaction]:
        delimiter = ";" if text.count(";") > text.count(",") else ","
        try:
            reader = csv.reader(io.StringIO(text), delimiter=delimiter)
            rows = list(reader)
        except Exception:
            return []

        if not rows:
            return []

        # Find header
        header_row_idx = 0
        for i, row in enumerate(rows[:10]):
            joined = " ".join(row).lower()
            if any(c in joined for c in ["tarih", "borç", "alacak", "evrak"]):
                header_row_idx = i
                break

        headers = rows[header_row_idx]
        date_col   = self._find_col(headers, self._DATE_COLS)
        debit_col  = self._find_col(headers, self._DEBIT_COLS)
        credit_col = self._find_col(headers, self._CREDIT_COLS)
        desc_col   = self._find_col(headers, self._DESC_COLS)
        ref_col    = self._find_col(headers, self._REF_COLS)
        acc_col    = self._find_col(headers, self._ACCOUNT_COLS)

        if date_col is None or (debit_col is None and credit_col is None):
            return []

        transactions: list[ParsedTransaction] = []
        for row in rows[header_row_idx + 1:]:
            if not row or all(not c.strip() for c in row):
                continue
            raw_date = row[date_col].strip() if date_col < len(row) else ""
            date = self.parse_turkish_date(raw_date)
            if not date:
                continue

            description = row[desc_col].strip() if desc_col is not None and desc_col < len(row) else ""
            reference   = row[ref_col].strip() if ref_col is not None and ref_col < len(row) else None
            account_code = row[acc_col].strip() if acc_col is not None and acc_col < len(row) else ""

            debit_cents  = 0
            credit_cents = 0
            if debit_col is not None and debit_col < len(row):
                v = self.parse_turkish_amount(row[debit_col].strip())
                if v:
                    debit_cents = v
            if credit_col is not None and credit_col < len(row):
                v = self.parse_turkish_amount(row[credit_col].strip())
                if v:
                    credit_cents = v

            tx_type, amount = self._resolve_tx_type(debit_cents, credit_cents, account_code)
            if amount <= 0:
                continue

            transactions.append(ParsedTransaction(
                date=date,
                description=description or f"Netsis {date.strftime('%d.%m.%Y')}",
                amount_cents=amount,
                tx_type=tx_type,
                currency="TRY",
                vendor=description[:50] if description else None,
                reference=reference or None,
                raw_row=delimiter.join(row),
            ))
        return transactions

    def _parse_fixed_width(self, text: str) -> list[ParsedTransaction]:
        """Fallback for Netsis fixed-width text reports."""
        pattern = re.compile(
            r"(\d{2}[./]\d{2}[./]\d{4})\s+"  # date
            r"(.{0,40}?)\s+"                   # description
            r"([\d.,]+)\s*"                    # amount1
            r"([\d.,]*)"                       # amount2
        )
        transactions: list[ParsedTransaction] = []
        for line in text.splitlines():
            m = pattern.search(line)
            if not m:
                continue
            date = self.parse_turkish_date(m.group(1))
            if not date:
                continue
            a1 = self.parse_turkish_amount(m.group(3)) or 0
            a2 = self.parse_turkish_amount(m.group(4)) or 0
            tx_type, amount = self._resolve_tx_type(a1, a2, "")
            if amount <= 0:
                continue
            transactions.append(ParsedTransaction(
                date=date,
                description=m.group(2).strip(),
                amount_cents=amount,
                tx_type=tx_type,
                currency="TRY",
                raw_row=line,
            ))
        return transactions

    @staticmethod
    def _resolve_tx_type(debit: int, credit: int, account_code: str) -> tuple[str, int]:
        """Same logic as Logo Tiger."""
        acc_prefix = account_code[:1] if account_code else ""
        if acc_prefix == "6":
            return ("expense", debit) if debit > 0 else ("income", credit)
        elif acc_prefix == "7":
            return ("income", credit) if credit > 0 else ("expense", debit)
        else:
            if credit > 0 and debit == 0:
                return "income", credit
            elif debit > 0 and credit == 0:
                return "expense", debit
            elif credit > 0 and debit > 0:
                net = credit - debit
                return ("income", net) if net > 0 else ("expense", abs(net))
        return "expense", 0
