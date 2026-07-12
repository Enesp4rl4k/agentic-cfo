"""İş Bankası statement parser."""
from __future__ import annotations
import re
from app.parsers.base import BankParser, ParsedStatement, ParsedTransaction


class IsBankParser(BankParser):
    bank_id = "isbank"
    bank_display_name = "Türkiye İş Bankası"
    _MARKERS = ["TÜRKİYE İŞ BANKASI", "İş Bankası", "ISBANK", "İşCep", "İşBankası"]

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
            statement.parse_warnings.append("No transactions extracted from İş Bankası statement.")
        return statement

    def _extract_account(self, text: str) -> str | None:
        m = re.search(r"Hesap\s+Numaras[ıi]\s*[:\-]?\s*(\d[\d\s\-]+)", text, re.IGNORECASE)
        return m.group(1).strip() if m else None

    def _parse_table(self, text: str) -> list[ParsedTransaction]:
        """
        İş Bankası format: DD.MM.YYYY  Açıklama  Borç  Alacak  Bakiye
        Borç = expense (positive value in debit col), Alacak = income (positive in credit col)
        """
        transactions: list[ParsedTransaction] = []
        row_pattern = re.compile(
            r"(\d{2}\.\d{2}\.\d{4})\s+"
            r"(.+?)\s+"
            r"([\d.,]+|-)\s+"    # debit or dash
            r"([\d.,]+|-)\s+"    # credit or dash
            r"([\d.,]+)\s*$",
            re.MULTILINE,
        )
        for m in row_pattern.finditer(text):
            date = self.parse_turkish_date(m.group(1))
            if not date:
                continue
            description = m.group(2).strip()
            debit_raw = m.group(3)
            credit_raw = m.group(4)

            if credit_raw and credit_raw != "-":
                amount = self.parse_turkish_amount(credit_raw)
                tx_type = "income"
            elif debit_raw and debit_raw != "-":
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
