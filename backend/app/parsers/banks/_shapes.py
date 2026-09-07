"""Statement layouts, shared by the banks that use them.

Yapı Kredi, QNB Finansbank and Enpara had three separate parser modules whose
logic was byte-identical once the bank name and the marker list were taken out
— 96–98% the same file, three times. Three copies of one regex is three places
a fix has to be remembered, and this codebase has already shipped two other
duplicated engines that drifted apart.

A bank belongs here when its statement has the same *shape*, not when it has
the same name. Adding a bank whose layout differs means a new shape, not a new
marker in an existing one.
"""
from __future__ import annotations

import re
from typing import ClassVar

from app.parsers.base import BankParser, ParsedStatement, ParsedTransaction

_ACCOUNT_RE = re.compile(
    r"Hesap\s+(?:No|Numarası|Numarasi)\s*[:\-]?\s*(\d[\d\s\-]+)", re.IGNORECASE
)


class SingleSignedColumnParser(BankParser):
    """Tarih · Açıklama · ±Tutar · Bakiye — one amount column carrying the sign.

    Subclasses declare `bank_id`, `bank_display_name` and `_MARKERS`. Nothing
    else: if a bank needs more than that, it does not have this shape.
    """

    # Declared here so a subclass that forgets it is a type error rather than an
    # AttributeError on the first statement someone uploads.
    _MARKERS: ClassVar[list[str]] = []

    # DD/MM/YYYY or DD.MM.YYYY, description, signed amount, running balance.
    _ROW = re.compile(
        r"(\d{2}[./]\d{2}[./]\d{4})\s+"
        r"(.+?)\s+"
        r"([+\-−]?[\d.,]+)\s+"
        r"([\d.,]+)\s*$",
        re.MULTILINE,
    )

    @classmethod
    def can_parse(cls, text: str) -> bool:
        upper = text.upper()
        return any(m.upper() in upper for m in cls._MARKERS)

    def parse(self, text: str, file_path: str = "") -> ParsedStatement:
        statement = ParsedStatement(
            bank_name=self.bank_display_name,
            account_number=self._extract_account(text),
            statement_period_start=None,
            statement_period_end=None,
        )
        statement.transactions = self._parse_table(text)
        if not statement.transactions:
            statement.parse_warnings.append(
                f"{self.bank_display_name} ekstresinden işlem çıkarılamadı."
            )
        return statement

    def _extract_account(self, text: str) -> str | None:
        m = _ACCOUNT_RE.search(text)
        return m.group(1).strip() if m else None

    def _parse_table(self, text: str) -> list[ParsedTransaction]:
        transactions: list[ParsedTransaction] = []
        for m in self._ROW.finditer(text):
            date = self.parse_turkish_date(m.group(1))
            if not date:
                continue

            amount_raw = m.group(3)
            amount_cents = self.parse_turkish_amount(amount_raw)
            if not amount_cents:
                continue

            # `parse_turkish_amount` returns a magnitude, so the sign is read
            # from the text. The three originals each also tested
            # `amount_cents < 0`, which could never be true.
            transactions.append(
                ParsedTransaction(
                    date=date,
                    description=m.group(2).strip(),
                    amount_cents=amount_cents,
                    tx_type="expense" if self.is_negative_amount(amount_raw) else "income",
                    currency="TRY",
                    balance_cents=self.parse_turkish_amount(m.group(4)),
                    raw_row=m.group(0),
                )
            )
        return transactions
