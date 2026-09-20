"""İşlem tarihi okunamadıysa bunu kaydeden tek yer.

A transaction whose date will not parse has to be given *some* date — the
column is not nullable and an entry has to exist to be reviewed. The mistake
was doing that silently: three separate places wrote `datetime.now(UTC)` on
failure, and from that moment nothing downstream could tell an invented date
from a real one.

It matters because the date decides the accounting period, and the period ends
up on a legal filing. A January transaction dated September is filed in the
wrong period, and the sealed defensibility packet says nothing is wrong.

So the estimate is still made — and it is always returned with a flag saying it
is an estimate. Callers persist that flag; the journal carries it; the e-Defter
refuses to file on it until a human has settled the period from the source
document. That is the one fact a reviewer can establish and the machine cannot.
"""
from __future__ import annotations

from datetime import UTC, datetime

# Formats a Turkish statement, ERP export or ISO source realistically carries.
_FORMATS = (
    "%Y-%m-%d",
    "%d.%m.%Y",
    "%d/%m/%Y",
    "%Y/%m/%d",
    "%d-%m-%Y",
)


def parse_transaction_date(
    raw: str | datetime | None, *, fallback: datetime | None = None
) -> tuple[datetime, bool]:
    """Return `(date, is_estimated)`.

    `is_estimated` is True whenever the value did not come from `raw` — because
    it was absent, or because nothing could read it. Never raises: a row with a
    broken date must still reach a reviewer rather than disappear.
    """
    if isinstance(raw, datetime):
        return (raw if raw.tzinfo else raw.replace(tzinfo=UTC)), False

    text = (raw or "").strip() if isinstance(raw, str) else ""
    if text:
        for fmt in _FORMATS:
            try:
                return datetime.strptime(text, fmt).replace(tzinfo=UTC), False
            except ValueError:
                continue
        try:
            parsed = datetime.fromisoformat(text)
            return (parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)), False
        except ValueError:
            pass

    return (fallback or datetime.now(UTC)), True
