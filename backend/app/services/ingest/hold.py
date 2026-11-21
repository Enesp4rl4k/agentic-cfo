"""Which extracted rows may enter the books now, and which wait for a person.

The principle: when data is missing or uncertain the system says so and asks; it
never fills the gap with a default that then looks like a fact.

**Currency.** A row's currency is, in this order: what the row states, what the
document states (`_detect_currency`), else the organisation's base currency —
marked `currency_assumed` so it is visible and correctable — else unknown, and an
unknown currency holds the row.

**The unit of a hold.** A row whose confidence is unknown (None) or below the
bar, or whose currency is unknown, waits. Rows that belong to one document (same
`document_id`) are held or released together: the two sides of one invoice must
not be split between the books and the review queue. A row with no document is
its own unit. The rest proceed: one weak row no longer holds the whole upload.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from app.core.row_confidence import needs_review, parse_confidence
from app.services.ingest.cells import _detect_currency

CONFIDENCE_UNKNOWN = "confidence_unknown"
CONFIDENCE_LOW = "confidence_low"
CURRENCY_UNKNOWN = "currency_unknown"
DIRECTION_UNKNOWN = "direction_unknown"
CURRENCY_DIFFERS = "currency_differs"
WITH_DOCUMENT = "document_held_together"


def resolve_currency(
    rows: list[dict[str, Any]], raw_text: str, base_currency: str | None
) -> None:
    """Give each row without a currency the document's, else the base's (assumed). In place."""
    stated = _detect_currency(raw_text)
    for row in rows:
        if str(row.get("currency") or "").strip():
            continue
        if stated:
            row["currency"] = stated
        elif base_currency:
            row["currency"] = base_currency
            row["currency_assumed"] = True
        else:
            row["currency"] = None


def row_reasons(row: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    confidence = parse_confidence(row.get("confidence"))
    if confidence is None:
        reasons.append(CONFIDENCE_UNKNOWN)
    elif needs_review(confidence):
        reasons.append(CONFIDENCE_LOW)
    if not str(row.get("currency") or "").strip():
        reasons.append(CURRENCY_UNKNOWN)
    if row.get("type") not in ("income", "expense"):
        reasons.append(DIRECTION_UNKNOWN)  # income or expense is never assumed
    return reasons


def split_uncertain(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(accepted, held). Held rows carry `hold_reasons`; a document is never split."""
    reasons = [row_reasons(r) for r in rows]
    # One run's totals are one currency. A row in another currency cannot be added
    # to them without a rate nobody here has chosen, so it waits for a person.
    counts = Counter(str(r["currency"]).strip().upper() for r in rows if str(r.get("currency") or "").strip())
    if len(counts) > 1:
        main = max(counts, key=lambda c: (counts[c], c == "TRY"))
        for row, why in zip(rows, reasons, strict=True):
            code = str(row.get("currency") or "").strip().upper()
            if code and code != main:
                why.append(CURRENCY_DIFFERS)
    held_documents = {
        r.get("document_id") for r, why in zip(rows, reasons, strict=True)
        if why and r.get("document_id")
    }
    accepted: list[dict[str, Any]] = []
    held: list[dict[str, Any]] = []
    for row, why in zip(rows, reasons, strict=True):
        if not why and row.get("document_id") in held_documents:
            why = [WITH_DOCUMENT]
        if why:
            held.append({**row, "hold_reasons": why})
        else:
            accepted.append(row)
    return accepted, held
