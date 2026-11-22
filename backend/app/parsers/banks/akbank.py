"""
Akbank statement parser.

Akbank PDF ekstrelerinde tipik format:
- Başlık: "AKBANK T.A.Ş." veya "Akbank"
- Tarih sütunu: DD.MM.YYYY
- Tablo: Tarih | Açıklama | Borç | Alacak | Bakiye
"""
from __future__ import annotations

import re
from datetime import UTC, datetime

from app.parsers.base import BankParser, ParsedStatement, ParsedTransaction
from app.parsers.direction import signed_money


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
            r"(\d{2}\.\d{2}\.\d{4})[ \t]+"   # date
            r"(.+?)[ \t]+"                     # description (non-greedy)
            r"(?:((?=[\d.,]*[.,])[\d.,]+)[ \t]+)?"            # debit (optional): a token ends at whitespace, never mid-number
            r"(?:((?=[\d.,]*[.,])[\d.,]+)[ \t]+)?"            # credit (optional)
            r"([+\-−]?[\d.,]+)[ \t]*$",      # balance
            re.MULTILINE,
        )
        for m in row_pattern.finditer(text):
            date = self.parse_turkish_date(m.group(1))
            estimated = date is None
            date = date or datetime.now(UTC)
            description = m.group(2).strip()
            debit_raw = m.group(3)
            credit_raw = m.group(4)

            # Which of the two optional columns an amount stood in is not recoverable from
            # text with the empty cell collapsed ("250,00  5.750,00"). The direction is left
            # open and read from the running balance (app.parsers.direction.settle_rows),
            # never assumed to be a debit.
            raw = debit_raw or credit_raw
            if not raw:
                # One number only: it is the balance, there is no amount to book. The line is left to
                # app.parsers.lines, which holds it with its raw text (never dropped, never booked at 0).
                continue
            amount = self.parse_turkish_amount(raw) or 0
            tx_type = ""

            transactions.append(ParsedTransaction(
                date=date,
                description=description,
                amount_cents=amount,
                tx_type=tx_type,
                balance_cents=signed_money(m.group(5)),
                raw_row=m.group(0), date_estimated=estimated,
                confidence_note="borç/alacak sütunu metinden ayırt edilemedi",
            ))

        return transactions
