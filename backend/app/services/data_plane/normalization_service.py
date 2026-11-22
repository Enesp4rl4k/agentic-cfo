"""Connector / scheduled-sync CSV -> canonical transaction rows, through the counting layer.

This used to be the one place a pulled row could become income by accident: `_to_cents` read "1.500" as 1,50,
`abc` and an empty cell as 0, and a zero or positive amount was always "income" with `confidence=90`.
Nothing here guesses any more. Every CSV row is counted (`services.ingest.feed`), and is either a canonical
row (every value the books need was stated and could be read) or a HELD row that is not written to the
canonical table and carries the raw values it was read from:

  amount     `parsers.direction.parse_money` (the one amount parser); missing, unreadable or ambiguous ("1.500"
             with no locale evidence) is held;
  direction  a `type` / `direction` column the source wrote (income, expense, gelir, gider, credit, debit); else
             the sign of the amount when the file is signed (some amount is negative); else the source's own
             semantics (`source_direction`: payroll is an expense, a paid Stripe invoice is income); else held;
  date       must read; an unreadable date is held, it is not today;
  currency   must be stated and be an ISO-4217 code; a source that states none is held (the upload pipeline
             applies the organisation's CONFIRMED base currency and marks it assumed; the canonical table has no
             such mark, so it takes only what the source said).
"""
from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.core.dates import parse_transaction_date
from app.services.ingest.feed import (
    EXPENSE,
    INCOME,
    Feed,
    FeedResult,
    direction_from_code,
    item_is_blank,
    read_money,
)

_INCOME_WORDS = (INCOME, "gelir", "credit", "alacak", "in")
_EXPENSE_WORDS = (EXPENSE, "gider", "debit", "borç", "borc", "out")
_HELD_AMOUNT = "?"
CURRENCY_MISSING = "currency_missing"


def _to_datetime(raw: str | None) -> tuple[datetime, bool]:
    """`(date, is_estimated)` — see app.core.dates for why the flag travels."""
    return parse_transaction_date(raw)


@dataclass
class CanonicalTxRow:
    source_record_id: str
    transaction_date: datetime
    # True when the source carried no readable date, so the one above is a
    # placeholder. See app.core.dates. A row with such a date is held, never written, so this is False
    # for every row this module returns; the field stays because the table has the column.
    date_is_estimated: bool
    amount_cents: int
    currency: str
    direction: str
    category: str | None
    counterparty: str | None
    description: str | None
    confidence: int | None


@dataclass
class NormalizedFeed:
    """What a CSV pull came to: rows that may be written, rows that wait for a person, and the counts."""
    rows: list[CanonicalTxRow]
    held: list[dict[str, Any]]            # feed rows (flags + raw values) that were NOT written
    feed: FeedResult
    # The file the analysis job reads: the pulled CSV with every held amount replaced by "?" so the upload
    # pipeline holds it too, and the raw values in its description. Identical bytes when nothing is held.
    job_csv: bytes = b""
    flagged_indexes: set[int] = field(default_factory=set)

    def outcome(self) -> dict[str, Any]:
        out = self.feed.outcome()
        # Canonical rows written + rows held = rows emitted: the same reconcile the upload pipeline runs.
        counts = dict(out["counts"] or {})
        counts["accepted"], counts["held"] = len(self.rows), len(self.held)
        out["counts"] = counts
        out["unaccounted"] = out["unaccounted"] + abs(counts.get("emitted", 0) - len(self.rows) - len(self.held))
        return out


def _direction(raw: dict[str, str], money_negative: bool, signed_file: bool, source_direction: str | None) -> str | None:
    said = (raw.get("type") or raw.get("direction") or raw.get("tip") or "").strip().lower()
    if said:
        return direction_from_code(said, _INCOME_WORDS, _EXPENSE_WORDS)     # an unknown word is held, not guessed
    if money_negative:
        return EXPENSE
    if signed_file:
        return INCOME
    return source_direction


def normalize_csv_transactions(
    *,
    csv_bytes: bytes,
    column_mapping: dict[str, str] | None = None,
    source_direction: str | None = None,
) -> NormalizedFeed:
    """Convert a connector/upload CSV payload into canonical rows (clean ones) and held rows (everything else)."""
    mapping = column_mapping or {}
    decoded = csv_bytes.decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(decoded.lstrip("﻿")))
    records = list(reader)
    feed = Feed("csv_sync")

    date_col = mapping.get("date", "date")
    amount_col = mapping.get("amount", "amount")
    desc_col = mapping.get("description", "description")
    category_col = mapping.get("category", "category")
    reference_col = mapping.get("reference", "reference")

    signed_file = any(read_money(r.get(amount_col)).negative for r in records)
    rows: list[CanonicalTxRow] = []
    held: list[dict[str, Any]] = []
    flagged: set[int] = set()

    for i, raw in enumerate(feed.each(records), start=1):
        if item_is_blank({k: v for k, v in raw.items() if k is not None}):
            feed.blank()
            continue
        money = read_money(raw.get(amount_col))
        evidence = {"amount": raw.get(amount_col), "date": raw.get(date_col), "type": raw.get("type"),
                    "currency": raw.get("currency"), "reference": raw.get(reference_col)}
        row = feed.add(
            amount=raw.get(amount_col), direction=_direction(raw, money.negative, signed_file, source_direction),
            date=raw.get(date_col), currency=raw.get("currency"), description=raw.get(desc_col) or "",
            reference=(raw.get(reference_col) or "").strip(), evidence=evidence,
            category=raw.get(category_col) or None, counterparty=raw.get("counterparty") or raw.get("vendor") or None,
        )
        if row["currency"] is None:
            row["feed_flags"].append(CURRENCY_MISSING)   # the canonical table takes only a currency the source stated
        if row["feed_flags"]:
            held.append(row)
            flagged.add(i)
            continue
        tx_date, estimated = _to_datetime(row["date"])
        source_record_id = row["reference"]
        if not source_record_id:
            fingerprint = "|".join(
                [raw.get(date_col) or "", raw.get(amount_col) or "", raw.get(desc_col) or "", str(i)]
            )
            source_record_id = hashlib.sha1(fingerprint.encode("utf-8"), usedforsecurity=False).hexdigest()[:24]
        rows.append(
            CanonicalTxRow(
                source_record_id=source_record_id,
                transaction_date=tx_date,
                date_is_estimated=estimated,
                amount_cents=int(row["amount_cents"]),
                currency=str(row["currency"]),
                direction=str(row["type"]),
                category=row["category"],
                counterparty=row["counterparty"],
                description=raw.get(desc_col) or None,
                # The source stated everything the books need; the figure is the source's, not a score of ours.
                confidence=None,
            )
        )
    return NormalizedFeed(rows, held, feed.result(), _job_csv(decoded, records, held, flagged, amount_col, desc_col),
                          flagged)


def _job_csv(
    decoded: str, records: list[dict[str, str]], held: list[dict[str, Any]], flagged: set[int],
    amount_col: str, desc_col: str,
) -> bytes:
    """The pulled CSV, with each held row's amount replaced by "?" and its raw values added to the description."""
    if not flagged:
        return decoded.encode("utf-8")
    header = list(records[0].keys()) if records else []
    if amount_col not in header:
        return decoded.encode("utf-8")
    shown = dict(zip(sorted(flagged), held, strict=True))
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=header, lineterminator="\n", extrasaction="ignore")
    writer.writeheader()
    for i, rec in enumerate(records, start=1):
        if i in shown:
            rec = {**rec, amount_col: _HELD_AMOUNT}
            if desc_col in header:
                rec[desc_col] = shown[i]["description"] or rec.get(desc_col, "")
        writer.writerow(rec)
    return out.getvalue().encode("utf-8")


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
        "date_is_estimated": row.date_is_estimated,
        "amount_cents": row.amount_cents,
        "currency": row.currency,
        "direction": row.direction,
        "category": row.category,
        "counterparty": row.counterparty,
        "description": row.description,
        "confidence": row.confidence,
    }
