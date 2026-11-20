"""Single cells of a statement: currency, amount in kuruş, sign, date.

Moved out of app/agents/data_ingestion.py unchanged (plan v11 A0.3); that module
re-exports what its callers import from it.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime


def _detect_currency(raw_text: str) -> str:
    """
    Detect the primary currency from document text.
    Returns ISO-4217 code: "TRY", "USD", "EUR", "GBP" etc.
    Defaults to "TRY" for documents that appear to be Turkish.
    """
    text_upper = raw_text[:2000].upper()  # Only scan the header

    # Explicit Turkish lira markers
    if any(marker in text_upper for marker in ["₺", "TL ", " TL\n", "TRY", "TÜRK LİRASI", "TÜRK LIRASI"]):
        return "TRY"
    # Euro markers
    if any(marker in text_upper for marker in ["€", "EUR ", " EUR\n", "EURO"]):
        return "EUR"
    # GBP
    if any(marker in text_upper for marker in ["£", "GBP ", " GBP\n"]):
        return "GBP"
    # USD
    if any(marker in text_upper for marker in ["$", "USD ", " USD\n", "DOLLAR"]):
        return "USD"

    # Turkish document heuristics (common Turkish words in financial docs)
    turkish_markers = ["HESAP", "BANKA", "FATURA", "TARİH", "TUTAR", "BORÇ", "ALACAK"]
    if sum(1 for m in turkish_markers if m in text_upper) >= 2:
        return "TRY"

    return "TRY"  # safe default for this product's target market


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
