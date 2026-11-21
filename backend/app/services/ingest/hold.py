"""Which extracted rows may enter the books now, and which wait for a person.

The principle: when data is missing or uncertain the system says so and asks; it
never fills the gap with a default that then looks like a fact.

**Currency.** A row's currency is, in this order: what the row states, what the
document states (`_detect_currency`), else the organisation's base currency —
but only one an owner/admin CONFIRMED (a stored default is not a choice), and
marked `currency_assumed` so it stays visible — else unknown, and an unknown
currency holds the row. A currency the row states is known, whatever it is: a
foreign-currency line is admitted with its own currency, not held for differing.

**The unit of a hold.** A row whose confidence is unknown (None) or below the
bar, whose currency, direction, amount or date is unknown, waits. Rows that belong to one document (same
`document_id`) are held or released together: the two sides of one invoice must
not be split between the books and the review queue. A row with no document is
its own unit. The rest proceed: one weak row no longer holds the whole upload.
"""
from __future__ import annotations

from typing import Any

from app.core.dates import parse_transaction_date
from app.core.row_confidence import needs_review, parse_confidence
from app.services.ingest.cells import _detect_currency

CONFIDENCE_UNKNOWN = "confidence_unknown"
CONFIDENCE_LOW = "confidence_low"
CURRENCY_UNKNOWN = "currency_unknown"
DIRECTION_UNKNOWN = "direction_unknown"
# The whole file's direction could not be placed (app.parsers.direction): one question for the file.
DIRECTION_FILE = "direction_file_unknown"
AMOUNT_UNREADABLE = "amount_unreadable"
DATE_UNREADABLE = "date_unreadable"
WITH_DOCUMENT = "document_held_together"


def resolve_currency(
    rows: list[dict[str, Any]], raw_text: str, base_currency: str | None
) -> None:
    """Give each row without a currency the document's, else the confirmed base's (assumed). In place."""
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
    if row.get("direction_file"):
        reasons.append(DIRECTION_FILE)
    elif row.get("type") not in ("income", "expense"):
        reasons.append(DIRECTION_UNKNOWN)  # income or expense is never assumed
    if "amount_cents" in row and row["amount_cents"] is None:
        reasons.append(AMOUNT_UNREADABLE)
    # A date nobody could read is not "today": the row waits (and so stays out of
    # every total) until a person gives it a date.
    if parse_transaction_date(row.get("transaction_date"))[1]:
        reasons.append(DATE_UNREADABLE)
    return reasons


def split_uncertain(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(accepted, held). Held rows carry `hold_reasons`; a document is never split."""
    reasons = [row_reasons(r) for r in rows]
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
