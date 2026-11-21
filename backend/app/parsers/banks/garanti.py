"""
Garanti BBVA statement parser.

Garanti PDF ekstrelerinde tipik format:
- Başlık: "GARANTİ BBVA" veya "T. GARANTİ BANKASI"
- Tablo: Tarih | Valör | Açıklama | Tutar | Bakiye
- Borç/alacak tek tutar sütununda, işaret ile ayrılır (- borç, + alacak)
"""
from __future__ import annotations

import re
from datetime import UTC, datetime

from app.parsers.base import BankParser, ParsedStatement, ParsedTransaction
from app.parsers.direction import sign_is_informative


class GarantiParser(BankParser):
    bank_id = "garanti"
    bank_display_name = "Garanti BBVA"

    _MARKERS = ["GARANTİ BBVA", "T. GARANTİ BANKASI", "Garanti Bankası", "GARANTI"]

    @classmethod
    def can_parse(cls, text: str) -> bool:
        return any(m.upper() in text.upper() for m in cls._MARKERS)

    def parse(self, text: str, file_path: str = "") -> ParsedStatement:
        statement = ParsedStatement(
            bank_name=self.bank_display_name,
            account_number=self._extract_account(text),
            statement_period_start=None,
            statement_period_end=None,
        )
        statement.transactions = self._parse_table(text)
        if not statement.transactions:
            statement.parse_warnings.append("No transactions extracted from Garanti statement.")
        return statement

    def _extract_account(self, text: str) -> str | None:
        m = re.search(r"Hesap\s+No\s*[:\-]?\s*(\d[\d\s]+)", text, re.IGNORECASE)
        return m.group(1).strip() if m else None

    def _parse_table(self, text: str) -> list[ParsedTransaction]:
        """
        Garanti format: DD.MM.YYYY  [DD.MM.YYYY]  Açıklama  [+/-]Tutar  Bakiye
        The amount column may have +/- prefix or a separate sign column.
        """
        transactions: list[ParsedTransaction] = []
        # Pattern: date, optional valor date, description, signed amount, balance
        row_pattern = re.compile(
            r"(\d{2}\.\d{2}\.\d{4})\s+"
            r"(?:\d{2}\.\d{2}\.\d{4}\s+)?"   # optional valor date
            r"(.+?)\s+"
            r"([+-]?[\d.,]+)\s+"
            r"([\d.,]+)\s*$",
            re.MULTILINE,
        )
        found = list(row_pattern.finditer(text))
        # A column of all-positive amounts says nothing about direction (app.parsers.direction).
        signed = sign_is_informative([m.group(3).startswith("-") for m in found])
        for m in found:
            self.matched += 1
            date = self.parse_turkish_date(m.group(1))
            estimated = date is None
            date = date or datetime.now(UTC)
            description = m.group(2).strip()
            amount_raw = m.group(3).lstrip("+")
            negative = amount_raw.startswith("-")
            amount = self.parse_turkish_amount(amount_raw.lstrip("-"))
            amount = amount or 0

            transactions.append(ParsedTransaction(
                date=date,
                description=description,
                amount_cents=amount,
                tx_type=("expense" if negative else "income") if signed else "",
                balance_cents=self.parse_turkish_amount(m.group(4)),
                raw_row=m.group(0), date_estimated=estimated,
            ))
        return transactions
