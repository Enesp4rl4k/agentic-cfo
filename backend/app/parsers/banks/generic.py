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

from app.core.row_confidence import parse_confidence
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
    "gelir/gider", "income", "expense", "debit/credit",
    "alacak/borç",
}
# Separate money-out / money-in columns: the column says the direction, not the sign.
_DEBIT_COLS = {"borç", "borc", "debit", "gider", "çıkış", "cikis", "para çıkışı", "para cikisi"}
_CREDIT_COLS = {"alacak", "credit", "gelir", "giriş", "giris", "para girişi", "para girisi"}
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


def _is_negative(raw: str) -> bool:
    """Whether an amount cell is written as negative: "-1.250,00", "(1.250,00)", "1.250,00-"."""
    r = raw.strip()
    return r.startswith("-") or r.endswith("-") or (r.startswith("(") and r.endswith(")"))


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
        elif norm in _DEBIT_COLS and "debit" not in roles:
            roles["debit"] = i
        elif norm in _CREDIT_COLS and "credit" not in roles:
            roles["credit"] = i
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

    split_columns = "debit" in roles and "credit" in roles
    if "date" not in roles or ("amount" not in roles and not split_columns):
        logger.debug("GenericParser CSV: missing date or amount column in %s", headers)
        return []

    transactions: list[ParsedTransaction] = []
    parser = GenericParser()
    body = [r for r in rows[header_idx + 1:] if len(r) > max(roles.values()) and any(c.strip() for c in r)]
    # A single amount column carries direction only if the file has both signs; a
    # column of all-positive amounts says nothing about which way the money went.
    signs = {_is_negative(r[roles["amount"]]) for r in body} if "amount" in roles else set()
    sign_is_direction = len(signs) == 2

    for row in body:
        raw_date = row[roles["date"]].strip()
        raw_amount = row[roles["amount"]].strip() if "amount" in roles else ""
        debit_cents = credit_cents = None
        if split_columns:
            debit_cents = parser.parse_turkish_amount(row[roles["debit"]].strip())
            credit_cents = parser.parse_turkish_amount(row[roles["credit"]].strip())
            raw_amount = row[roles["credit"]].strip() if credit_cents else row[roles["debit"]].strip()
        description = row[roles.get("description", -1)].strip() if "description" in roles else ""
        raw_type = row[roles.get("type", -1)].strip() if "type" in roles else ""
        vendor = row[roles.get("vendor", -1)].strip() if "vendor" in roles else None

        date = parser.parse_turkish_date(raw_date)
        if not date:
            continue

        amount = parser.parse_turkish_amount(raw_amount)
        if not amount:
            continue

        # Direction is read from the document, never assumed. In order: a type
        # column, separate debit/credit columns, the sign of a signed column.
        # When none of them decides it, the row leaves with no direction ("")
        # and is held for a person (app.services.ingest.hold).
        tx_type = ""
        if raw_type:
            rt = raw_type.lower()
            if any(w in rt for w in ("gelir", "alacak", "income", "credit", "tahsilat", "giriş")):
                tx_type = "income"
            elif any(w in rt for w in ("gider", "borç", "expense", "debit", "ödeme", "çıkış")):
                tx_type = "expense"
        if not tx_type and split_columns:
            if credit_cents and not debit_cents:
                tx_type = "income"
            elif debit_cents and not credit_cents:
                tx_type = "expense"
        if not tx_type and sign_is_direction:
            tx_type = "expense" if _is_negative(raw_amount) else "income"

        transactions.append(ParsedTransaction(
            date=date,
            description=description or raw_date,
            amount_cents=amount,
            tx_type=tx_type,
            vendor=vendor or None,
            raw_row=",".join(row),
            # A read direction is rule-derived (not certain); an absent one is unknown.
            confidence=0.95 if tx_type else None,
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
                # Neither direction nor confidence is assumed for an LLM-read row:
                # an unstated one is held for review (app.services.ingest.hold).
                tx_type=str(item.get("type") or ""),
                currency=str(item.get("currency") or ""),
                vendor=item.get("vendor"),
                raw_row=str(item),
                confidence=parse_confidence(item.get("confidence")),
            ))

        return transactions
