"""What an upload did, in numbers and words a person can read.

"N kayıt işlendi, M kayıt incelemenizi bekliyor" — and, separately, the rows that
were read but cannot count yet: no readable date (they sit in the job's
transaction list marked `date_is_estimated`, outside the ledger), or a currency
the document did not state (marked `currency_assumed`).
"""
from __future__ import annotations

from typing import Any

from app.core.dates import parse_transaction_date


def ingest_summary(accepted: list[dict[str, Any]], held: list[dict[str, Any]]) -> dict[str, Any]:
    undated = sum(1 for r in accepted if parse_transaction_date(r.get("transaction_date"))[1])
    assumed = sum(1 for r in accepted if r.get("currency_assumed"))
    parts = [f"{len(accepted)} kayıt işlendi"]
    if held:
        parts.append(f"{len(held)} kayıt incelemenizi bekliyor (toplamlara dahil değil)")
    if undated:
        parts.append(
            f"{undated} kaydın tarihi okunamadığı için deftere ve toplamlara alınmadı "
            "(işlem listesinde 'tarih tahmini' olarak işaretli)"
        )
    if assumed:
        parts.append(f"{assumed} kaydın para birimi belgede yok, kuruluşun ana para birimi varsayıldı")
    return {
        "processed": len(accepted),
        "held": len(held),
        "undated": undated,
        "currency_assumed": assumed,
        "summary": "; ".join(parts) + ".",
    }
