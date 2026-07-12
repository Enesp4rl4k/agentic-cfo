"""Ziraat Bankası statement parser."""
from __future__ import annotations
import re
from app.parsers.base import BankParser, ParsedStatement, ParsedTransaction


class ZiraatParser(BankParser):
    bank_id = "ziraat"
    bank_display_name = "Ziraat Bankası"
    _MARKERS = ["ZİRAAT BANKASI", "T.C. ZİRAAT", "Ziraat Bankası", "ZIRAAT"]

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
            statement.parse_warnings.append("No transactions extracted from Ziraat statement.")
        return statement

    def _extract_account(self, text: str) -> str | None:
        m = re.search(r"Hesap\s+No\s*[:\-]?\s*(\d[\d\s\-]+)", text, re.IGNORECASE)
        return m.group(1).strip() if m else None

    def _parse_table(self, text: str) -> list[ParsedTransaction]:
        """
        Ziraat format: DD.MM.YYYY  Açıklama  Tutar  Borç/Alacak  Bakiye
        Some Ziraat statements use a single signed amount column.
        """
        transactions: list[ParsedTransaction] = []

        # Try two-column format (borç/alacak separate)
        two_col = re.compile(
            r"(\d{2}\.\d{2}\.\d{4})\s+(.+?)\s+([\d.,]+|-)\s+([\d.,]+|-)\s+([\d.,]+)\s*$",
            re.MULTILINE,
        )
        for m in two_col.finditer(text):
            date = self.parse_turkish_date(m.group(1))
            if not date:
                continue
            description = m.group(2).strip()
            borç_raw, alacak_raw = m.group(3), m.group(4)

            if alacak_raw != "-":
                amount = self.parse_turkish_amount(alacak_raw)
                tx_type = "income"
            elif borç_raw != "-":
                amount = self.parse_turkish_amount(borç_raw)
                tx_type = "expense"
            else:
                continue

            if not amount:
                continue
            transactions.append(ParsedTransaction(
                date=date, description=description,
                amount_cents=amount, tx_type=tx_type, raw_row=m.group(0),
            ))

        if transactions:
            return transactions

        # Fallback: signed single-amount column
        one_col = re.compile(
            r"(\d{2}\.\d{2}\.\d{4})\s+(.+?)\s+([+-]?[\d.,]+)\s+([\d.,]+)\s*$",
            re.MULTILINE,
        )
        for m in one_col.finditer(text):
            date = self.parse_turkish_date(m.group(1))
            if not date:
                continue
            description = m.group(2).strip()
            raw = m.group(3)
            negative = raw.startswith("-")
            amount = self.parse_turkish_amount(raw.lstrip("+-"))
            if not amount:
                continue
            transactions.append(ParsedTransaction(
                date=date, description=description,
                amount_cents=amount,
                tx_type="expense" if negative else "income",
                raw_row=m.group(0),
            ))

        return transactions
