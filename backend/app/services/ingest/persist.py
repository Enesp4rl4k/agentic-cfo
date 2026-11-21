"""One extracted row as a `Transaction`: the single place that builds it."""
from __future__ import annotations

from datetime import date
from typing import Any

from app.core.dates import parse_transaction_date
from app.core.row_confidence import parse_confidence
from app.models.transaction import Transaction


def build_transaction(job_id: str, tx_data: dict[str, Any]) -> Transaction:
    """The row as the pipeline produced it. The caller has already settled currency and direction.

    Nothing here invents a value that would look like a fact: confidence stays
    None when unknown, the currency is required (KeyError means a row skipped
    the hold), and an unreadable date is flagged `date_is_estimated`.
    """
    # An unreadable date still becomes today's — the column is not nullable and
    # the row has to exist to be reviewed — but the row says so, because this
    # date decides the accounting period and the period ends up on the e-Defter.
    tx_date, tx_date_estimated = parse_transaction_date(tx_data.get("transaction_date"))
    return Transaction(
        job_id=job_id,
        amount_kurus=tx_data.get("amount_cents") or 0,
        currency=str(tx_data["currency"]).strip().upper(),
        currency_assumed=bool(tx_data.get("currency_assumed")),
        type=tx_data["type"],
        category=tx_data.get("category", "other_expense"),
        description=tx_data.get("description", ""),
        vendor=tx_data.get("vendor"),
        transaction_date=tx_date,
        date_is_estimated=tx_date_estimated,
        # As the document stated them; None when it did not.
        kdv_kurus=tx_data.get("kdv_cents"),
        stopaj_kurus=tx_data.get("stopaj_cents"),
        raw_text=tx_data.get("raw_text"),
        confidence=parse_confidence(tx_data.get("confidence")),
        category_source=tx_data.get("category_source"),
        account_code=tx_data.get("account_code"),
        document_id=tx_data.get("document_id"),
        due_date=date.fromisoformat(tx_data["due_date"]) if tx_data.get("due_date") else None,
        payment_note=tx_data.get("payment_note"),
        counterparty=tx_data.get("counterparty"),
    )
