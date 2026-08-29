from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


def _to_datetime(raw: str | None) -> datetime:
    if not raw:
        return datetime.now(UTC)
    candidates = ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%Y/%m/%d")
    for fmt in candidates:
        try:
            return datetime.strptime(raw.strip(), fmt).replace(tzinfo=UTC)
        except Exception:
            continue
    try:
        return datetime.fromisoformat(raw).astimezone(UTC)
    except Exception:
        return datetime.now(UTC)


def _to_cents(raw: str | None) -> int:
    if not raw:
        return 0
    txt = raw.strip().replace(" ", "")
    txt = txt.replace("₺", "").replace("$", "").replace("€", "")
    if "," in txt and "." in txt and txt.find(".") < txt.find(","):
        txt = txt.replace(".", "").replace(",", ".")
    elif "," in txt and "." not in txt:
        txt = txt.replace(",", ".")
    try:
        return round(float(txt) * 100)
    except Exception:
        return 0


@dataclass
class CanonicalTxRow:
    source_record_id: str
    transaction_date: datetime
    amount_cents: int
    currency: str
    direction: str
    category: str | None
    counterparty: str | None
    description: str | None
    confidence: int | None


def normalize_csv_transactions(
    *,
    csv_bytes: bytes,
    column_mapping: dict[str, str] | None = None,
) -> list[CanonicalTxRow]:
    """
    Convert connector/upload CSV payload into canonical transaction rows.
    """
    mapping = column_mapping or {}
    decoded = csv_bytes.decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(decoded))
    rows: list[CanonicalTxRow] = []

    date_col = mapping.get("date", "date")
    amount_col = mapping.get("amount", "amount")
    desc_col = mapping.get("description", "description")
    category_col = mapping.get("category", "category")
    reference_col = mapping.get("reference", "reference")

    for i, raw in enumerate(reader, start=1):
        amount_cents = _to_cents(raw.get(amount_col))
        direction = "income" if amount_cents >= 0 else "expense"
        source_record_id = (raw.get(reference_col) or "").strip()
        if not source_record_id:
            fingerprint = "|".join(
                [
                    raw.get(date_col) or "",
                    raw.get(amount_col) or "",
                    raw.get(desc_col) or "",
                    str(i),
                ]
            )
            source_record_id = hashlib.sha1(fingerprint.encode("utf-8")).hexdigest()[:24]
        rows.append(
            CanonicalTxRow(
                source_record_id=source_record_id,
                transaction_date=_to_datetime(raw.get(date_col)),
                amount_cents=abs(amount_cents),
                currency=(raw.get("currency") or "TRY").strip() or "TRY",
                direction=direction,
                category=(raw.get(category_col) or None),
                counterparty=(raw.get("counterparty") or raw.get("vendor") or None),
                description=(raw.get(desc_col) or None),
                confidence=90,
            )
        )
    return rows


def to_insert_dict(
    *,
    org_id: str,
    source_type: str,
    sync_run_id: str | None,
    row: CanonicalTxRow,
) -> dict[str, Any]:
    return {
        "org_id": org_id,
        "source_type": source_type,
        "source_record_id": row.source_record_id,
        "sync_run_id": sync_run_id,
        "transaction_date": row.transaction_date,
        "amount_cents": row.amount_cents,
        "currency": row.currency,
        "direction": row.direction,
        "category": row.category,
        "counterparty": row.counterparty,
        "description": row.description,
        "confidence": row.confidence,
    }

