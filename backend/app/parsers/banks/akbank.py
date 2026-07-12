"""
Akbank statement parser.

Akbank PDF ekstrelerinde tipik format:
- Başlık: "AKBANK T.A.Ş." veya "Akbank"
- Tarih sütunu: DD.MM.YYYY
- Tablo: Tarih | Açıklama | Borç | Alacak | Bakiye
"""
from __future__ import annotations

import re
from datetime import timezone

from app.parsers.base import BankParser, ParsedStatement, ParsedTransaction


class AkbankParser(BankParser):
    bank_id = "akbank"
    bank_display_name = "Akbank"

    # Heuristic markers found in Akbank PDFs
    _MARKERS = ["AKBANK T.A.Ş", "Akbank Direkt", "AKBANK", "akbank"]

    @classmethod
    def can_parse(cls, text: str) -> bool:
        return any(m in text for m in cls._MARKERS)

    def parse(self, text: str, file_path: str = "") -> ParsedStatement:
        statement = ParsedStatement(
            bank_name=self.bank_display_name,
            account_number=self._extract_account(text),
            statement_period_start=None,
            statement_period_end=None,
        )

        # Try table-based extraction first
        transactions = self._parse_table(text)
        if not transactions:
            statement.parse_warnings.append(
                "Could not extract table rows — table layout may differ from expected."
            )

        statement.transactions = transactions
        return statement

    def _extract_account(self, text: str) -> str | None:
        m = re.search(r"Hesap\s+No[:\s]+(\d[\d\s\-]+)", text, re.IGNORECASE)
        return m.group(1).strip() if m else None

    def _parse_table(self, text: str) -> list[ParsedTransaction]:
        """
        Akbank ekstresi satır formatı (tipik):
        DD.MM.YYYY  Açıklama metni  [borç tutarı]  [alacak tutarı]  bakiye
        """
        transactions: list[ParsedTransaction] = []
        # Match: date, description, optional debit, optional credit
        row_pattern = re.compile(
            r"(\d{2}\.\d{2}\.\d{4})\s+"   # date
            r"(.+?)\s+"                     # description (non-greedy)
            r"([\d.,]+)?\s*"                # debit (optional)
            r"([\d.,]+)?\s*"                # credit (optional)
            r"([\d.,]+)\s*$",               # balance
            re.MULTILINE,
        )
        for m in row_pattern.finditer(text):
            date = self.parse_turkish_date(m.group(1))
            if not date:
                continue
            description = m.group(2).strip()
            debit_raw = m.group(3)
            credit_raw = m.group(4)

            if credit_raw:
                amount = self.parse_turkish_amount(credit_raw)
                tx_type = "income"
            elif debit_raw:
                amount = self.parse_turkish_amount(debit_raw)
                tx_type = "expense"
            else:
                continue

            if not amount:
                continue

            transactions.append(ParsedTransaction(
                date=date,
                description=description,
                amount_cents=amount,
                tx_type=tx_type,
                raw_row=m.group(0),
            ))

        return transactions
