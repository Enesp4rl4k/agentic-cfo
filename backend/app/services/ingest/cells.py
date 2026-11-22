"""Single cells of a statement: currency, amount in kuruş, sign, date.

Moved out of app/agents/data_ingestion.py unchanged (plan v11 A0.3); that module
re-exports what its callers import from it.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

# A currency the document STATES. Symbols and codes only count as whole tokens: "ENTRY" and
# "COUNTRY" contain TRY and say nothing about lira.
_PARA_BIRIMI_ALANI = re.compile(
    r"(?:hesap\s+para\s+birimi|para\s+birimi|d[oö]viz\s+cinsi|d[oö]viz\s+kodu|currency|account\s+currency)"
    r"\s*[:=\-]?\s*([A-Za-z₺$€£]{1,12})",
    re.IGNORECASE,
)
_ALAN_DEGERLERI = {
    "TL": "TRY", "TRY": "TRY", "TRL": "TRY", "TURK LIRASI": "TRY", "TÜRK LİRASI": "TRY", "₺": "TRY",
    "USD": "USD", "$": "USD", "DOLAR": "USD", "EUR": "EUR", "EURO": "EUR", "€": "EUR",
    "GBP": "GBP", "£": "GBP", "STERLIN": "GBP",
}
_ISARETLER = (
    ("TRY", re.compile(r"(?<![A-Z0-9])(?:TL|TRY)(?![A-Z0-9])|₺|T[ÜU]RK L[İI]RASI")),
    ("EUR", re.compile(r"(?<![A-Z0-9])(?:EUR|EURO)(?![A-Z0-9])|€")),
    ("GBP", re.compile(r"(?<![A-Z0-9])GBP(?![A-Z0-9])|£")),
    ("USD", re.compile(r"(?<![A-Z0-9])USD(?![A-Z0-9])|\$|(?<![A-Z0-9])DOLLAR(?![A-Z0-9])")),
)


def _detect_currency(raw_text: str) -> str | None:
    """
    The currency a document *states*, as an ISO-4217 code, or None.

    In this order: a header field naming it ("Hesap Para Birimi: USD", "Döviz Cinsi: EUR"), else the
    one currency whose symbol or code appears in the header (₺, TL, TRY, €, EUR, £, GBP, $, USD)
    as a whole token. A document that merely reads as Turkish has not said TRY, and used to be
    given it; a document that mentions two currencies (a "USD ALIŞ" line on a lira statement) has
    not said which one its amounts are in, so it states none. The caller decides what to do then
    (organisation base currency, marked as assumed, else the row waits for a person).
    """
    head = raw_text[:2000]
    if field := _PARA_BIRIMI_ALANI.search(head):
        value = field.group(1).strip().upper()
        if value in _ALAN_DEGERLERI:
            return _ALAN_DEGERLERI[value]
    upper = head.upper()
    found = {code for code, pattern in _ISARETLER if pattern.search(upper)}
    return found.pop() if len(found) == 1 else None


def _parse_amount(raw: str) -> int | None:
    """Parse an amount string into the smallest currency unit (cents/kurus).

    Handles:
      - "1000.50"  → 100050
      - "1.000,50" → 100050 (European format: dot=thousands, comma=decimal)
      - "1,000.50" → 100050 (Anglo format: comma=thousands, dot=decimal)
      - "₺1,500"   → 150000 (TRY symbol + Anglo format)
    """
    # Strip currency symbols and whitespace
    s = re.sub(r"[^\d,.]", "", raw)
    if not s:
        return None

    # Detect format: if both separators present, identify which is decimal
    has_dot   = "." in s
    has_comma = "," in s

    if has_dot and has_comma:
        # Whichever appears last is the decimal separator
        last_dot   = s.rfind(".")
        last_comma = s.rfind(",")
        if last_comma > last_dot:
            # European format: 1.000,50 → remove dots, replace comma with dot
            s = s.replace(".", "").replace(",", ".")
        else:
            # Anglo format: 1,000.50 → remove commas
            s = s.replace(",", "")
    elif has_comma and not has_dot:
        # Could be decimal comma (1000,50) or thousands comma (1,500)
        # If there are exactly 3 digits after the comma, treat as thousands sep
        parts = s.split(",")
        if len(parts) == 2 and len(parts[1]) == 3:
            s = s.replace(",", "")  # thousands separator
        else:
            s = s.replace(",", ".")  # decimal separator
    # If only dots, leave as-is

    try:
        return round(float(s) * 100)
    except (ValueError, TypeError):
        return None


def _is_negative(raw: str) -> bool:
    """Whether an amount is written as money out: "-1.500", "1.500-", "(1.500)".

    ``_parse_amount`` returns a magnitude, so the sign has to be read here —
    without it a CSV with no type column booked every payment as revenue.
    """
    t = raw.strip()
    return t.startswith("-") or t.endswith("-") or (t.startswith("(") and t.endswith(")"))


def _parse_date(raw: str) -> datetime | None:
    # Excel date cells arrive as "2024-01-03 00:00:00".
    formats = ["%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y",
               "%Y-%m-%d %H:%M:%S", "%d.%m.%Y %H:%M:%S"]
    for fmt in formats:
        try:
            return datetime.strptime(raw.strip(), fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None
