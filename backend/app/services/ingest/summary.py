"""What an upload did, in numbers and words a person can read.

"N kayıt işlendi, M kayıt incelemenizi bekliyor". A row whose date could not be
read is not "processed": it waits among the held rows (reason "tarih okunamadı")
and is in no total. A currency the document did not state, filled from the
company's confirmed currency, is marked `currency_assumed`.
"""
from __future__ import annotations

from typing import Any


def ingest_summary(
    accepted: list[dict[str, Any]], registered: dict[str, Any], counts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    held_now = int(registered.get("new", 0)) + int(registered.get("already_waiting", 0))
    assumed = sum(1 for r in accepted if r.get("currency_assumed"))
    counts = counts or {}
    read = int(counts.get("read", 0))
    skipped = int(counts.get("summary_skipped", 0))
    transfers = int(counts.get("account_skipped", 0))
    lost = int(counts.get("unaccounted", 0))
    parts = []
    if read:
        # Every row the reader was handed is in exactly one of these: nothing disappears unseen.
        head = f"{read} satır okundu: {len(accepted)} kaydedildi, {held_now} kararınızı bekliyor, {skipped} özet satırı atlandı"
        if transfers:
            head += f", {transfers} geçiş/kapanış kaydı atlandı"
        parts.append(head)
    else:
        parts.append(f"{len(accepted)} kayıt işlendi")
        if held_now:
            parts.append(f"{held_now} kayıt incelemenizi bekliyor (toplamlara dahil değil)")
    if lost:
        parts.append(f"{lost} satır hesaba katılamadı; dosya gözden geçirilmeli")
    if counts.get("reader_failed"):
        parts.append("bu dosya beklenen biçimde okunamadı, alternatif okuyucu kullanıldı")
    if registered.get("currency_unknown"):
        parts.append(
            f"{registered['currency_unknown']} kaydın para birimi bilinmiyor; şirketin para birimini "
            "onaylarsanız bu kayıtlar serbest bırakılır"
        )
    if registered.get("already_rejected"):
        parts.append(f"{registered['already_rejected']} kayıt daha önce reddedildiği için tekrar sorulmadı")
    if assumed:
        parts.append(f"{assumed} kaydın para birimi belgede yok, şirketin onaylı para birimi kullanıldı")
    return {
        "processed": len(accepted),
        "held": held_now,
        "currency_assumed": assumed,
        "already_rejected": int(registered.get("already_rejected", 0)),
        "rows_read": read,
        "summary_lines_skipped": skipped,
        "skipped_lines": list(counts.get("summary_lines", [])),
        "account_lines_skipped": transfers,
        "unaccounted": lost,
        "reader_fallback": bool(counts.get("reader_failed")),
        "summary": "; ".join(parts) + ".",
    }
