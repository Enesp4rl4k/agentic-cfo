"""The period a statement says it covers, read from the header of the file's own text.

Bank and ERP exports usually open with it ("Dönem: 01.01.2026 - 31.03.2026", "Tarih Aralığı",
"Başlangıç Tarihi / Bitiş Tarihi"). It says which days the statement is MEANT to cover; whether the
rows actually reach them is checked against the data (`app.services.coverage.apply_period`). Row
parsing is not touched: this reads the text the readers already produced.

Only the header counts, and only a labelled period:
- the header is the lines BEFORE the table's column-header line (Tarih; Açıklama; Tutar ...). With
  no recognisable column-header line there is no header, so nothing is read: a row description such
  as "Dönem 01.01.2026 - 31.01.2026 aidat" is never a statement period;
- the period must sit on a line with a period label (`Dönem`, `Tarih Aralığı`, `Hesap/Ekstre
  Dönemi`, `Başlangıç Tarihi` + `Bitiş Tarihi`); a print date or a bare pair of dates is not one;
- it is ignored when inconsistent: two different periods, an end before the start, longer than ten
  years, or a transaction dated outside it.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

MAX_PERIOD_DAYS = 3660

_D = r"(\d{1,2}[./]\d{1,2}[./]\d{4}|\d{4}-\d{2}-\d{2})"
_DASH = r"\s*(?:-|–|—|~|/|;|\t|ile|ila|to)\s*"
_LABELLED = re.compile(
    r"(?:dönem|donem|tarih\s*aralığı|tarih\s*araligi|period|date\s*range)"
    r"[^\n\d]{0,30}" + _D + _DASH + _D,
    re.IGNORECASE,
)
_START = re.compile(r"(?:başlangıç|baslangic|başlama|baslama|start|from)\s*tarihi?[\s:;=,\"]*" + _D, re.IGNORECASE)
_END = re.compile(r"(?:bitiş|bitis|bitim|end|to)\s*tarihi?[\s:;=,\"]*" + _D, re.IGNORECASE)

# The cells of a table's column-header line, as the repo's exports write them (Tarih;Açıklama;Tutar;
# Bakiye;Para Birimi, Tarih;Fiş No;Hesap Kodu;Açıklama;Borç;Alacak;Bakiye, date,amount,description...).
_COLUMNS = frozenset({
    "tarih", "işlem tarihi", "valör", "date", "açıklama", "aciklama", "description", "tutar", "amount",
    "bakiye", "balance", "borç", "borc", "alacak", "debit", "credit", "fiş no", "hesap kodu",
    "para birimi", "currency", "tip", "type", "kategori", "category", "reference", "referans",
})


def _header_lines(text: str) -> list[str] | None:
    """The lines before the table's column-header line; None when the text has no such line."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        cells = [c.strip().strip('"').lower() for c in re.split(r"[;,\t|]|\s{2,}", line)]
        if len(cells) >= 3 and sum(c in _COLUMNS for c in cells) >= 3:
            return lines[:i]
    return None


def _parse(text: str) -> date | None:
    try:
        if len(text) == 10 and text[4] == "-":
            return date.fromisoformat(text)
        day, month, year = re.split(r"[./]", text)
        return date(int(year), int(month), int(day))
    except ValueError:
        return None


def _candidates(head: str) -> set[tuple[date, date]]:
    found: set[tuple[date, date]] = set()
    for m in _LABELLED.finditer(head):
        a, b = _parse(m.group(1)), _parse(m.group(2))
        if a and b:
            found.add((a, b))
    start, end = _START.search(head), _END.search(head)
    if start and end:
        a, b = _parse(start.group(1)), _parse(end.group(1))
        if a and b:
            found.add((a, b))
    return found


def stated_period(text: str, transaction_dates: list[str] | None = None) -> dict[str, Any] | None:
    """{"start", "end"} (ISO dates) the file's header states, or None when it states none it can stand by."""
    header = _header_lines(text)
    if header is None:
        return None
    candidates = _candidates("\n".join(header))
    if len(candidates) != 1:
        return None  # nothing stated, or two periods: not proof of either
    start, end = next(iter(candidates))
    if start > end or (end - start).days > MAX_PERIOD_DAYS:
        return None
    dates = sorted(str(d)[:10] for d in (transaction_dates or []) if d)
    if dates and (dates[0] < start.isoformat() or dates[-1] > end.isoformat()):
        return None
    return {"start": start.isoformat(), "end": end.isoformat()}
