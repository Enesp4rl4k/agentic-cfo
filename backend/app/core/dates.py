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

from datetime import UTC, datetime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Formats a Turkish statement, ERP export or ISO source realistically carries.
_FORMATS = (
    "%Y-%m-%d",
    "%d.%m.%Y",
    "%d/%m/%Y",
    "%Y/%m/%d",
    "%d-%m-%Y",
)


def istanbul() -> tzinfo:
    """The company's calendar: Europe/Istanbul (fixed UTC+3 where the tz database is missing)."""
    try:
        return ZoneInfo("Europe/Istanbul")
    except ZoneInfoNotFoundError:   # slim images carry no tz database; Turkey has been UTC+3 since 2016
        return timezone(timedelta(hours=3))


def _calendar_day(value: datetime) -> datetime:
    """Midnight UTC of the calendar day the document states.

    The ledger's one date convention (`ledger.month_of`, period locks, fingerprints): a row's
    `transaction_date` is the document's calendar day at 00:00 UTC, never a clock time. A
    timestamp that carries an offset is read on the Istanbul calendar first, so 00:30 on the
    1st (+03:00) is the 1st, not the previous UTC day. A naive one already is a calendar day.
    """
    if value.tzinfo is not None:
        value = value.astimezone(istanbul())
    return datetime(value.year, value.month, value.day, tzinfo=UTC)


def parse_transaction_date(
    raw: str | datetime | None, *, fallback: datetime | None = None
) -> tuple[datetime, bool]:
    """Return `(date, is_estimated)`.

    `is_estimated` is True whenever the value did not come from `raw` — because
    it was absent, or because nothing could read it. Never raises: a row with a
    broken date must still reach a reviewer rather than disappear.
    """
    if isinstance(raw, datetime):
        return _calendar_day(raw), False

    text = (raw or "").strip() if isinstance(raw, str) else ""
    if text:
        for fmt in _FORMATS:
            try:
                return datetime.strptime(text, fmt).replace(tzinfo=UTC), False
            except ValueError:
                continue
        try:
            parsed = datetime.fromisoformat(text)
            return _calendar_day(parsed), False
        except ValueError:
            pass

    return (fallback or datetime.now(UTC)), True
