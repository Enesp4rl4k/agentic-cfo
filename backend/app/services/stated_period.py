"""The period a statement says it covers, read from the header of the file's own text.

Bank and ERP exports usually open with it ("Dönem: 01.01.2026 - 31.03.2026", "Tarih Aralığı",
"Başlangıç Tarihi / Bitiş Tarihi"). It is the strongest evidence of which days a statement covers: a
statement for January with no transaction on the 31st still covers the 31st. Row parsing is not
touched: this reads the text the readers already produced.

Only a header counts. The period is taken from the first lines, and is ignored when it is not
consistent: two different periods in the header, an end before the start, longer than ten years, or
a transaction dated outside it (the header is then about something else).
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

HEADER_CHARS = 4000  # the header region of the text; a transaction row is never read as a period
MAX_PERIOD_DAYS = 3660

_D = r"(\d{1,2}[./]\d{1,2}[./]\d{4}|\d{4}-\d{2}-\d{2})"
_DASH = r"\s*(?:-|–|—|~|/|;|	|ile|ila|to)\s*"
_LABELLED = re.compile(
    r"(?:dönem|donem|tarih\s*aralığı|tarih\s*araligi|period|date\s*range|ekstre\s*dönemi|hesap\s*dönemi)"
    r"[^\n\d]{0,30}" + _D + _DASH + _D,
    re.IGNORECASE,
)
_BARE_LINE = re.compile(r"^[^\w\n]*" + _D + _DASH + _D + r"[^\w\n]*$", re.IGNORECASE | re.MULTILINE)
_START = re.compile(r"(?:başlangıç|baslangic|başlama|baslama|start|from)\s*tarihi?[\s:;=,\"]*" + _D, re.IGNORECASE)
_END = re.compile(r"(?:bitiş|bitis|bitim|end|to)\s*tarihi?[\s:;=,\"]*" + _D, re.IGNORECASE)


def _parse(text: str) -> date | None:
    try:
        if "-" in text and len(text) == 10 and text[4] == "-":
            return date.fromisoformat(text)
        day, month, year = re.split(r"[./]", text)
        return date(int(year), int(month), int(day))
    except ValueError:
        return None


def _candidates(head: str) -> set[tuple[date, date]]:
    found: set[tuple[date, date]] = set()
    for pattern in (_LABELLED, _BARE_LINE):
        for m in pattern.finditer(head):
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
    candidates = _candidates(text[:HEADER_CHARS])
    if len(candidates) != 1:
        return None  # nothing stated, or two periods: not proof of either
    start, end = next(iter(candidates))
    if start > end or (end - start).days > MAX_PERIOD_DAYS:
        return None
    dates = sorted(str(d)[:10] for d in (transaction_dates or []) if d)
    if dates and (dates[0] < start.isoformat() or dates[-1] > end.isoformat()):
        return None
    return {"start": start.isoformat(), "end": end.isoformat()}
