"""
Mikro Yazılım parser — Türkiye'de KOBİ segmentinde yaygın muhasebe/ERP.

Mikro export formatları:
  - Hesap Hareketleri Listesi: Tarih | Evrak No | Fiş Türü | Açıklama | Borç | Alacak | Bakiye
  - Cari Kart Hareketleri: Tarih | Belge No | Açıklama | Borç | Alacak | Bakiye
  - Kasa/Banka Hareketi: Tarih | No | Açıklama | Giriş | Çıkış | Bakiye

Mikro başlık satırında "MİKRO", "MIKRO" veya "Mikro Yazılım"
veya "Hesap Hareketleri" gibi ifadeler içerir.

Not: Mikro'da "Giriş" = income (para girişi), "Çıkış" = expense (para çıkışı)
"""
from __future__ import annotations

import csv
import io
import re

from app.parsers.base import BankParser, ParsedStatement, ParsedTransaction


class MikroParser(BankParser):
    bank_id = "mikro"
    bank_display_name = "Mikro Yazılım"

    _MARKERS = [
        "MİKRO", "MIKRO", "Mikro Yazılım", "MIKRO YAZILIM",
        "Mikro ERP", "MIKRO ERP",
        "GİRİŞ", "ÇIKIŞ", "Giris", "Cikis",
        "Cari Kart", "CARİ KART",
    ]

    _DATE_COLS    = ["tarih", "işlem tarihi", "belge tarihi", "date"]
    _INCOME_COLS  = ["giriş", "giris", "alacak", "income", "tutar (g)"]
    _EXPENSE_COLS = ["çıkış", "cikis", "borç", "expense", "tutar (c)"]
    _DESC_COLS    = ["açıklama", "aciklama", "description", "işlem"]
    _REF_COLS     = ["evrak no", "belge no", "fiş no", "no", "referans"]

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
        statement.transactions = transactions

        if not transactions:
            statement.parse_warnings.append("Mikro: İşlem bulunamadı.")
        if transactions:
            dates = [t.date for t in transactions]
            statement.statement_period_start = min(dates)
            statement.statement_period_end   = max(dates)
        return statement

    def _extract_account(self, text: str) -> str | None:
        m = re.search(r"(?:Cari|Hesap)\s*(?:Kodu|No|Kart)[:\s]*([A-Z0-9./\-]{3,20})", text, re.IGNORECASE)
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
            rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
        except Exception:
            return []

        if not rows:
            return []

        header_idx = 0
        for i, row in enumerate(rows[:10]):
            joined = " ".join(row).lower()
            if any(c in joined for c in ["tarih", "giriş", "çıkış", "borç", "alacak"]):
                header_idx = i
                break

        headers = rows[header_idx]
        date_col    = self._find_col(headers, self._DATE_COLS)
        income_col  = self._find_col(headers, self._INCOME_COLS)
        expense_col = self._find_col(headers, self._EXPENSE_COLS)
        desc_col    = self._find_col(headers, self._DESC_COLS)
        ref_col     = self._find_col(headers, self._REF_COLS)

        if date_col is None or (income_col is None and expense_col is None):
            return []

        transactions: list[ParsedTransaction] = []
        for row in rows[header_idx + 1:]:
            if not row or all(not c.strip() for c in row):
                continue
            raw_date = row[date_col].strip() if date_col < len(row) else ""
            date = self.parse_turkish_date(raw_date)
            if not date:
                continue

            description = row[desc_col].strip() if desc_col is not None and desc_col < len(row) else ""
            reference   = row[ref_col].strip() if ref_col is not None and ref_col < len(row) else None

            income  = 0
            expense = 0
            if income_col is not None and income_col < len(row):
                v = self.parse_turkish_amount(row[income_col].strip())
                if v:
                    income = v
            if expense_col is not None and expense_col < len(row):
                v = self.parse_turkish_amount(row[expense_col].strip())
                if v:
                    expense = v

            if income > 0 and expense == 0:
                tx_type, amount = "income", income
            elif expense > 0 and income == 0:
                tx_type, amount = "expense", expense
            elif income > 0 and expense > 0:
                net = income - expense
                tx_type, amount = ("income", net) if net > 0 else ("expense", abs(net))
            else:
                continue

            transactions.append(ParsedTransaction(
                date=date,
                description=description or f"Mikro {date.strftime('%d.%m.%Y')}",
                amount_cents=amount,
                tx_type=tx_type,
                currency="TRY",
                vendor=description[:50] if description else None,
                reference=reference or None,
                raw_row=delimiter.join(row),
            ))
        return transactions
