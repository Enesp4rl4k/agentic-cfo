"""Shared CSV helpers for connector pulls."""
from __future__ import annotations

import csv
import io
from typing import Any


def transactions_to_csv(transactions: list[dict[str, Any]]) -> bytes:
    if not transactions:
        return b""

    all_keys = list({k for tx in transactions for k in tx})
    priority = ["date", "amount", "description", "category", "reference"]
    ordered_keys = [k for k in priority if k in all_keys] + [
        k for k in all_keys if k not in priority
    ]

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=ordered_keys, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(transactions)
    return buf.getvalue().encode("utf-8")
