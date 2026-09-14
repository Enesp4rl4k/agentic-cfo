"""
Generic parser — rule-based CSV first, LLM fallback for everything else.

Strategy:
  1. If text looks like a CSV (has commas/tabs, header row) → try rule-based extraction
     using Turkish/English column name mapping (free, fast, reliable for standard exports)
  2. If rule-based yields 0 transactions → fall back to LLM extraction
  3. LLM is ONLY called when rule-based fails — avoids unnecessary API costs
"""
from __future__ import annotations

import csv
import io
import json
import logging
import re

from app.parsers.base import BankParser, ParsedStatement, ParsedTransaction

logger = logging.getLogger(__name__)


# ── Turkish/English column name mapping ──────────────────────────────────────
# Maps normalized column names to their semantic role.
# Each role has a list of accepted column names (case-insensitive, whitespace-stripped).

_DATE_COLS = {
    "tarih", "date", "işlem tarihi", "islem tarihi", "value date",
    "valör", "valor", "trans. date", "transaction date", "dt",
}
_AMOUNT_COLS = {
    "tutar", "amount", "miktar", "toplam", "total", "fiyat", "price",
    "gelir/gider", "gelir", "gider", "income", "expense", "debit/credit",
    "alacak/borç", "alacak", "borç",
}
_DESC_COLS = {
    "açıklama", "aciklama", "description", "detay", "detail", "narration",
    "işlem açıklaması", "islem aciklamasi", "transaction", "trans. desc",
    "bilgi", "bilgi notu", "notes",
}
_TYPE_COLS = {
    "tür", "tur", "type", "işlem tipi", "islem tipi", "kategori", "category",
}
_VENDOR_COLS = {
    "satıcı", "satici", "vendor", "karşı hesap", "karsi hesap",
    "müşteri", "musteri", "gönderen", "gonderen", "alıcı", "alici",
}


def _normalize(s: str) -> str:
    return s.strip().lower()


def _detect_column_roles(headers: list[str]) -> dict[str, int]:
    """
    Map semantic roles to column indices.
    Returns dict with keys: "date", "amount", "description", "type", "vendor"
    """
    roles: dict[str, int] = {}
    for i, h in enumerate(headers):
        norm = _normalize(h)
        if norm in _DATE_COLS and "date" not in roles:
            roles["date"] = i
        elif norm in _AMOUNT_COLS and "amount" not in roles:
            roles["amount"] = i
        elif norm in _DESC_COLS and "description" not in roles:
            roles["description"] = i
        elif norm in _TYPE_COLS and "type" not in roles:
            roles["type"] = i
        elif norm in _VENDOR_COLS and "vendor" not in roles:
            roles["vendor"] = i
    return roles


def _parse_csv_transactions(text: str) -> list[ParsedTransaction]:
    """
    Rule-based CSV extraction.
    Returns empty list if columns can't be mapped or no rows parsed.
    """
    # Detect delimiter
    delimiter = ","
    if text.count("\t") > text.count(","):
        delimiter = "\t"
    elif text.count(";") > text.count(","):
        delimiter = ";"

    try:
        reader = csv.reader(io.StringIO(text), delimiter=delimiter)
        rows = list(reader)
    except Exception:
        return []

    if len(rows) < 2:
        return []

    # Find header row — first row with >= 2 non-empty cells
    header_idx = 0
    for i, row in enumerate(rows[:5]):
        if sum(1 for c in row if c.strip()) >= 2:
            header_idx = i
            break

    headers = rows[header_idx]
    roles = _detect_column_roles(headers)

    if "date" not in roles or "amount" not in roles:
        logger.debug("GenericParser CSV: missing date or amount column in %s", headers)
        return []

    transactions: list[ParsedTransaction] = []
    parser = GenericParser()

    for row in rows[header_idx + 1:]:
        if len(row) <= max(roles.values()):
            continue
        if not any(c.strip() for c in row):
            continue  # blank row

        raw_date = row[roles["date"]].strip()
        raw_amount = row[roles["amount"]].strip()
        description = row[roles.get("description", -1)].strip() if "description" in roles else ""
        raw_type = row[roles.get("type", -1)].strip() if "type" in roles else ""
        vendor = row[roles.get("vendor", -1)].strip() if "vendor" in roles else None

        date = parser.parse_turkish_date(raw_date)
        if not date:
            continue

        amount = parser.parse_turkish_amount(raw_amount)
        if not amount:
            continue

        # Determine income/expense
        tx_type = "expense"
        if raw_type:
            rt = raw_type.lower()
            if any(w in rt for w in ("gelir", "alacak", "income", "credit", "tahsilat", "giriş")):
                tx_type = "income"
            elif any(w in rt for w in ("gider", "borç", "expense", "debit", "ödeme", "çıkış")):
                tx_type = "expense"
        # If no type column: amount sign may indicate direction
        # (negative = expense handled by caller via parse_turkish_amount which strips sign)

        transactions.append(ParsedTransaction(
            date=date,
            description=description or raw_date,
            amount_cents=amount,
            tx_type=tx_type,
            vendor=vendor or None,
            raw_row=",".join(row),
        ))

    return transactions


class GenericParser(BankParser):
    bank_id = "generic"
    bank_display_name = "Generic"

    @classmethod
    def can_parse(cls, text: str) -> bool:
        # Generic always matches — it's the fallback
        return True

    def parse(self, text: str, file_path: str = "") -> ParsedStatement:
        statement = ParsedStatement(
            bank_name="Generic CSV",
            account_number=None,
            statement_period_start=None,
            statement_period_end=None,
        )

        # ── Strategy 1: rule-based CSV extraction ────────────────────────────
        # Try this first — free, fast, works for standard exports without LLM
        if self._looks_like_csv(text):
            transactions = _parse_csv_transactions(text)
            if transactions:
                logger.info(
                    "GenericParser: rule-based CSV extracted %d transactions",
                    len(transactions),
                )
                statement.transactions = transactions
                statement.bank_name = "Generic CSV (rule-based)"
                return statement
            else:
                statement.parse_warnings.append(
                    "CSV detected but column mapping failed — falling back to LLM."
                )

        # ── Strategy 2: LLM fallback ──────────────────────────────────────────
        statement.parse_warnings.append(
            "No structured parser matched. Using LLM extraction (lower reliability)."
        )
        try:
            transactions = self._extract_via_llm(text)
            statement.transactions = transactions
            if transactions:
                logger.info(
                    "GenericParser: LLM extracted %d transactions", len(transactions)
                )
        except Exception as exc:
            logger.exception("GenericParser LLM extraction failed")
            statement.parse_warnings.append(f"LLM extraction failed: {exc}")

        return statement

    @staticmethod
    def _looks_like_csv(text: str) -> bool:
        """Heuristic: does the text look like a CSV/TSV?"""
        lines = [l for l in text.splitlines() if l.strip()]
        if len(lines) < 2:
            return False
        # Has consistent delimiter count across first few lines
        for delim in (",", "\t", ";"):
            counts = [line.count(delim) for line in lines[:5]]
            if counts and min(counts) >= 1 and max(counts) - min(counts) <= 2:
                return True
        return False

    def _extract_via_llm(self, text: str) -> list[ParsedTransaction]:
        """
        LLM extraction from unstructured text — the last-resort fallback.

        Runs the async Model Gateway from this sync ``BankParser.parse`` context
        via a fresh event loop. When already inside a running loop (which the
        production ingestion path is — and it has its own gateway-backed LLM
        extraction), this returns [] and lets that path handle it.
        """
        import asyncio

        from app.platform.model_gateway import LLMUnavailable, complete_text

        system = (
            "You are a financial data extraction specialist. "
            "Extract all financial transactions from the document text as a JSON array. "
            "Each transaction must have: "
            "date (DD.MM.YYYY), amount (numeric, no symbols), "
            "type ('income' or 'expense'), description (string), "
            "vendor (string or null), confidence (0-1). "
            "Return ONLY a valid JSON array. No markdown, no explanation."
        )

        try:
            asyncio.get_running_loop()
            logger.debug("GenericParser._extract_via_llm called from async context — deferring")
            return []
        except RuntimeError:
            pass

        try:
            content = asyncio.run(
                complete_text(
                    task="simple_extraction",
                    system_prompt=system,
                    prompt=f"Document:\n\n{text[:6000]}",
                    temperature=0.0,
                    max_tokens=4096,
                )
            ).strip()
        except LLMUnavailable:
            return []

        # Strip markdown code fences
        content = re.sub(r"^```[a-z]*\n?", "", content)
        content = re.sub(r"\n?```$", "", content)

        raw_list = json.loads(content)
        transactions: list[ParsedTransaction] = []

        for item in raw_list:
            date = self.parse_turkish_date(str(item.get("date", "")))
            if not date:
                continue
            amount = self.parse_turkish_amount(str(item.get("amount", "")))
            if not amount:
                continue
            transactions.append(ParsedTransaction(
                date=date,
                description=str(item.get("description", "")),
                amount_cents=amount,
                tx_type=item.get("type", "expense"),
                vendor=item.get("vendor"),
                raw_row=str(item),
            ))

        return transactions
