"""
Paraşüt parser — Türkiye'nin önde gelen cloud muhasebe platformu.
Özellikle startup ekosisteminde yaygın.

Paraşüt CSV export formatları (app.parasut.com'dan indirilen):

1. İşlem Raporu (Transaction Report):
   Tarih,Tip,Kategori,Açıklama,Tutar,Döviz,Döviz Tutarı,Hesap,Referans

2. Banka Hareketi:
   Tarih,İşlem Türü,Açıklama,Tutar,Bakiye,Hesap

3. Fatura Listesi:
   Tarih,Fatura No,Müşteri/Tedarikçi,Açıklama,Tutar,KDV,Toplam,Durum

Paraşüt'ün CSV'si her zaman UTF-8 BOM ile gelir ve başlık satırında
"Paraşüt" veya "parasut.com" veya "İşlem Tarihi" içerir.

İşlem tipleri:
  "Gelir" → income
  "Gider" → expense
  "Satış Faturası" → income
  "Alış Faturası" → expense
  "Kasa Girişi" → income
  "Kasa Çıkışı" → expense
"""
from __future__ import annotations

import csv
import io
import re

from app.parsers.base import BankParser, ParsedStatement, ParsedTransaction


# Paraşüt işlem tipi → tx_type mapping
_TYPE_MAP: dict[str, str] = {
    "gelir":               "income",
    "gider":               "expense",
    "satış faturası":      "income",
    "satis faturasi":      "income",
    "alış faturası":       "expense",
    "alis faturasi":       "expense",
    "kasa girişi":         "income",
    "kasa cikisi":         "expense",
    "kasa çıkışı":         "expense",
    "banka girişi":        "income",
    "banka çıkışı":        "expense",
    "banka cikisi":        "expense",
    "tahsilat":            "income",
    "ödeme":               "expense",
    "odeme":               "expense",
    "masraf":              "expense",
    "transfer girişi":     "income",
    "transfer çıkışı":     "expense",
}


def _map_type(raw: str) -> str | None:
    raw_lower = raw.strip().lower()
    for key, tx_type in _TYPE_MAP.items():
        if key in raw_lower:
            return tx_type
    return None


class ParasutParser(BankParser):
    bank_id = "parasut"
    bank_display_name = "Paraşüt"

    _MARKERS = [
        "Paraşüt", "PARAŞÜT", "parasut", "PARASUT",
        "parasut.com", "app.parasut.com",
        "İşlem Tarihi", "Islem Tarihi",
        # Paraşüt column headers
        "Fatura No", "Müşteri/Tedarikçi", "Musteri/Tedarikci",
        "Hesap Adı", "KDV Tutarı",
    ]

    @classmethod
    def can_parse(cls, text: str) -> bool:
        text_check = text[:2000]  # Check first 2KB only for speed
        text_upper = text_check.upper()
        return any(m.upper() in text_upper for m in cls._MARKERS)

    def parse(self, text: str, file_path: str = "") -> ParsedStatement:
        # Strip UTF-8 BOM if present
        if text.startswith("\ufeff"):
            text = text[1:]

        statement = ParsedStatement(
            bank_name=self.bank_display_name,
            account_number=None,
            statement_period_start=None,
            statement_period_end=None,
        )

        # Try transaction report format first, then invoice format
        transactions = self._parse_transaction_report(text)
        if not transactions:
            transactions = self._parse_invoice_list(text)
        if not transactions:
            transactions = self._parse_bank_movement(text)

        statement.transactions = transactions

        if not transactions:
            statement.parse_warnings.append(
                "Paraşüt: İşlem bulunamadı. CSV formatını kontrol edin."
            )
        if transactions:
            dates = [t.date for t in transactions]
            statement.statement_period_start = min(dates)
            statement.statement_period_end   = max(dates)
        return statement

    def _find_col(self, headers: list[str], candidates: list[str]) -> int | None:
        headers_lower = [h.strip().lower() for h in headers]
        for cand in candidates:
            cand_lower = cand.lower()
            for i, h in enumerate(headers_lower):
                if cand_lower in h or h in cand_lower:
                    return i
        return None

    def _parse_transaction_report(self, text: str) -> list[ParsedTransaction]:
        """
        Parse Paraşüt transaction report CSV.
        Columns: Tarih, Tip, Kategori, Açıklama, Tutar, Döviz, Hesap, Referans
        """
        try:
            rows = list(csv.reader(io.StringIO(text), delimiter=","))
        except Exception:
            return []

        if not rows:
            return []

        # Find header
        header_idx = 0
        for i, row in enumerate(rows[:5]):
            joined = " ".join(row).lower()
            if "tarih" in joined and ("tip" in joined or "tutar" in joined):
                header_idx = i
                break

        headers = rows[header_idx]
        date_col  = self._find_col(headers, ["tarih", "işlem tarihi", "date"])
        type_col  = self._find_col(headers, ["tip", "type", "işlem türü", "tür"])
        desc_col  = self._find_col(headers, ["açıklama", "aciklama", "description"])
        amt_col   = self._find_col(headers, ["tutar", "amount", "toplam", "net tutar"])
        acc_col   = self._find_col(headers, ["hesap", "account", "hesap adı"])
        ref_col   = self._find_col(headers, ["referans", "fatura no", "belge no"])

        if date_col is None or amt_col is None:
            return []

        transactions: list[ParsedTransaction] = []
        for row in rows[header_idx + 1:]:
            if not row or len(row) <= max(c for c in [date_col, amt_col] if c is not None):
                continue

            raw_date = row[date_col].strip() if date_col < len(row) else ""
            date = self.parse_turkish_date(raw_date)
            if not date:
                continue

            raw_type = row[type_col].strip() if type_col is not None and type_col < len(row) else ""
            description = row[desc_col].strip() if desc_col is not None and desc_col < len(row) else ""
            reference   = row[ref_col].strip() if ref_col is not None and ref_col < len(row) else None
            account     = row[acc_col].strip() if acc_col is not None and acc_col < len(row) else ""

            raw_amt = row[amt_col].strip() if amt_col < len(row) else ""
            # Paraşüt uses negative for outflows
            is_negative = raw_amt.startswith("-")
            amount_cents = self.parse_turkish_amount(raw_amt)
            if not amount_cents or amount_cents == 0:
                continue

            # Determine type
            tx_type = _map_type(raw_type)
            if tx_type is None:
                tx_type = "expense" if is_negative else "income"

            vendor = self._extract_vendor(description, account)

            transactions.append(ParsedTransaction(
                date=date,
                description=description or raw_type or f"Paraşüt {date.strftime('%d.%m.%Y')}",
                amount_cents=abs(amount_cents),
                tx_type=tx_type,
                currency="TRY",
                vendor=vendor,
                reference=reference or None,
                raw_row=",".join(row),
            ))
        return transactions

    def _parse_invoice_list(self, text: str) -> list[ParsedTransaction]:
        """Parse Paraşüt invoice list export."""
        try:
            rows = list(csv.reader(io.StringIO(text), delimiter=","))
        except Exception:
            return []

        if not rows:
            return []

        header_idx = 0
        for i, row in enumerate(rows[:5]):
            joined = " ".join(row).lower()
            if "fatura" in joined or "müşteri" in joined:
                header_idx = i
                break

        headers = rows[header_idx]
        date_col   = self._find_col(headers, ["tarih", "fatura tarihi"])
        desc_col   = self._find_col(headers, ["açıklama", "müşteri", "tedarikçi", "musteri"])
        total_col  = self._find_col(headers, ["toplam", "fatura tutarı", "tutar"])
        type_col   = self._find_col(headers, ["tür", "tip", "fatura türü", "type"])

        if date_col is None or total_col is None:
            return []

        transactions: list[ParsedTransaction] = []
        for row in rows[header_idx + 1:]:
            if not row:
                continue
            raw_date = row[date_col].strip() if date_col < len(row) else ""
            date = self.parse_turkish_date(raw_date)
            if not date:
                continue

            raw_type = row[type_col].strip() if type_col is not None and type_col < len(row) else ""
            description = row[desc_col].strip() if desc_col is not None and desc_col < len(row) else ""
            amount_cents = self.parse_turkish_amount(row[total_col].strip()) if total_col < len(row) else None
            if not amount_cents or amount_cents == 0:
                continue

            tx_type = _map_type(raw_type) or "income"

            transactions.append(ParsedTransaction(
                date=date,
                description=description or f"Paraşüt Fatura {date.strftime('%d.%m.%Y')}",
                amount_cents=abs(amount_cents),
                tx_type=tx_type,
                currency="TRY",
                vendor=description[:50] if description else None,
                raw_row=",".join(row),
            ))
        return transactions

    def _parse_bank_movement(self, text: str) -> list[ParsedTransaction]:
        """Parse Paraşüt bank movement export."""
        try:
            rows = list(csv.reader(io.StringIO(text), delimiter=","))
        except Exception:
            return []

        if not rows:
            return []

        header_idx = 0
        for i, row in enumerate(rows[:5]):
            joined = " ".join(row).lower()
            if "tarih" in joined and "bakiye" in joined:
                header_idx = i
                break

        headers = rows[header_idx]
        date_col   = self._find_col(headers, ["tarih", "işlem tarihi"])
        desc_col   = self._find_col(headers, ["açıklama", "işlem türü"])
        amount_col = self._find_col(headers, ["tutar", "amount"])

        if date_col is None or amount_col is None:
            return []

        transactions: list[ParsedTransaction] = []
        for row in rows[header_idx + 1:]:
            if not row:
                continue
            raw_date = row[date_col].strip() if date_col < len(row) else ""
            date = self.parse_turkish_date(raw_date)
            if not date:
                continue

            description = row[desc_col].strip() if desc_col is not None and desc_col < len(row) else ""
            raw_amt = row[amount_col].strip() if amount_col < len(row) else ""
            is_negative = raw_amt.startswith("-")
            amount_cents = self.parse_turkish_amount(raw_amt)
            if not amount_cents:
                continue

            tx_type = "expense" if is_negative else "income"

            transactions.append(ParsedTransaction(
                date=date,
                description=description or f"Paraşüt Banka {date.strftime('%d.%m.%Y')}",
                amount_cents=abs(amount_cents),
                tx_type=tx_type,
                currency="TRY",
                raw_row=",".join(row),
            ))
        return transactions

    @staticmethod
    def _extract_vendor(description: str, account: str) -> str | None:
        if account and account not in ("Nakit", "Banka"):
            return account[:50]
        if description:
            return description[:50]
        return None
