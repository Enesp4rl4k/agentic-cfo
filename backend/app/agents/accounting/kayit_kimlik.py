"""The stable id of a journal entry: the same source transaction gives the same `kayit_id` on every run."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

# Fixed namespace for journal entry ids. Changing it orphans every SMMM
# decision ever recorded, so it never changes.
_KAYIT_NS = uuid.UUID("6f1d3c2e-4b7a-5e9f-8a21-0c5d7e3b9f10")


def _gun(value: Any) -> str | None:
    """The calendar day, whatever shape the date arrived in.

    The in-memory pipeline passes a string, a row read back from the database a
    datetime; both name the same day and must give the same id.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text).date().isoformat()
    except ValueError:
        return text


def _kaynak_parmak_izi(tx: dict[str, Any]) -> str:
    """What identifies a source transaction across re-runs.

    Not `Transaction.id`: re-analysing a job deletes and re-inserts its
    transactions with fresh ids. The content does not change.
    """
    amount = tx.get("amount_kurus", tx.get("amount_cents"))
    parts = (
        _gun(tx.get("transaction_date")),
        abs(int(amount)) if amount is not None else None,
        tx.get("type"),
        tx.get("description"),
        tx.get("vendor"),
        tx.get("document_id"),
        tx.get("counterparty"),
    )
    base = "|".join("" if p is None else str(p) for p in parts)
    # The currency tells apart the same payment in two currencies (one agent run per currency, `sira`
    # restarting at 0 in each). A lira row, or one that names no currency (a row stored before currencies
    # were kept), adds nothing: its id, and every approval pointing at it, must not change.
    if "currency" in tx and (code := str(tx["currency"] or "").strip().upper()) != "TRY":
        return f"{base}|para_birimi={code or '?'}"
    return base


def kararli_kayit_id(tx: dict[str, Any], sira: int = 0) -> str:
    """A journal entry id that is the same every time the same transaction is journalled.

    The id was a fresh uuid4 per run. The accountant's decisions
    (`SMMMOnayKaydi.kayit_id`) point at it, so every re-run left each approval
    pointing at an entry that no longer existed: approved entries silently
    dropped out of the e-Defter and went back into the review queue.
    `sira` separates identical transactions in the same file (two equal
    payments on one day): the n-th occurrence gets n.
    """
    return str(uuid.uuid5(_KAYIT_NS, f"{_kaynak_parmak_izi(tx)}#{sira}"))
