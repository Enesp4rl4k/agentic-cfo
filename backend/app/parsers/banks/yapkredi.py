"""Yapı Kredi statement parser."""
from __future__ import annotations

import re
from app.parsers.base import BankParser, ParsedStatement, ParsedTransaction


class YapiKrediParser(BankParser):
    bank_id = "yapkredi"
    bank_display_name = "Yapı ve Kredi Bankası"
    _MARKERS = ["YAPI VE KREDİ", "YAPI KREDİ", "Yapi Kredi", "YapiKredi", "YKB"]

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
            statement.parse_warnings.append("No transactions extracted from Yapı Kredi statement.")
        return statement

    def _extract_account(self, text: str) -> str | None:
        m = re.search(r"Hesap\s+(?:No|Numarası)\s*[:\-]?\s*(\d[\d\s\-]+)", text, re.IGNORECASE)
        return m.group(1).strip() if m else None

    def _parse_table(self, text: str) -> list[ParsedTransaction]:
        """
        Yapı Kredi format: DD/MM/YYYY or DD.MM.YYYY  İşlem Açıklaması  Borç / Alacak Tutar  Bakiye
        """
        transactions: list[ParsedTransaction] = []
        row_pattern = re.compile(
            r"(\d{2}[./]\d{2}[./]\d{4})\s+"
            r"(.+?)\s+"
            r"([+-]?[\d.,]+)\s+"
            r"([\d.,]+)\s*$",
            re.MULTILINE,
        )
        for m in row_pattern.finditer(text):
            date = self.parse_turkish_date(m.group(1))
            if not date:
                continue
            description = m.group(2).strip()
            amount_raw = m.group(3)
            balance_raw = m.group(4)

            amount = self.parse_turkish_amount(amount_raw)
            if amount is None or amount == 0:
                continue

            tx_type = "expense" if amount_raw.startswith("-") or amount < 0 else "income"
            balance = self.parse_turkish_amount(balance_raw)

            transactions.append(
                ParsedTransaction(
                    date=date,
                    description=description,
                    amount=abs(amount),
                    transaction_type=tx_type,
                    balance=balance,
                    raw_category=None,
                )
            )
        return transactions
