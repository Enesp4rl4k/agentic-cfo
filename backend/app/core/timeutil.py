"""Timezone normalisation for values read back from the database.

SQLite has no native timezone type: a column declared `DateTime(timezone=True)`
round-trips as a **naive** datetime, while PostgreSQL returns an aware one. Code
that subtracts a stored timestamp from `datetime.now(UTC)` therefore works in
production and raises `TypeError: can't subtract offset-naive and offset-aware
datetimes` on a dev/SQLite box — and only once rows actually exist, so it hides
behind empty tables.

Wrap any datetime that came out of the DB in `as_utc()` before arithmetic.
"""
from __future__ import annotations

from datetime import UTC, datetime


def as_utc(value: datetime | None) -> datetime | None:
    """Return `value` as timezone-aware UTC. Naive input is assumed to be UTC."""
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
