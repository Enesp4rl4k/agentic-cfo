"""The period a ledger reading covers (plan v10 gap G8, step S1.4).

Split from `ledger.py`: what a period is, how the default one is chosen, and what a screen
is told about it. The reading itself (`ledger.company_rows`) applies it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.core.dates import istanbul

DEFAULT_PERIOD_MONTHS = 12
_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def add_months(month: str, n: int) -> str:
    """"2026-01" plus n months (n may be negative)."""
    index = int(month[:4]) * 12 + int(month[5:7]) - 1 + n
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


@dataclass(frozen=True)
class Period:
    """A requested period, in whole months ("YYYY-MM", both ends included).

    Months are the ledger's own (`month_of`: the UTC day of the row, the same months a
    period lock closes). Either end may be left out: no `end` is the month of the latest
    data, no `start` is `DEFAULT_PERIOD_MONTHS` months ending at `end`.
    """

    start: str | None = None
    end: str | None = None

    def __post_init__(self) -> None:
        for m in (self.start, self.end):
            if m is not None and not _MONTH_RE.match(m):
                raise ValueError(f"not a month (YYYY-MM): {m!r}")
        if self.start and self.end and self.start > self.end:
            raise ValueError("period start is after its end")


@dataclass(frozen=True)
class LedgerPeriod:
    """The period actually used, for the screen: what it covers and what exists beyond it."""

    start: str | None
    end: str | None
    months: int                 # months inside it that hold a counted row
    label: str | None           # "2025-02 – 2026-01"
    is_default: bool            # nobody asked for it: the last 12 months of data
    available_start: str | None  # first and last month with any counted row, and how many
    available_end: str | None
    available_months: int
    # Rows dated after the current month (a typo, a post-dated invoice): out of the default
    # period, in any explicit one, and reported so a screen can say they exist.
    future_rows: int
    future_latest: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "start": self.start, "end": self.end, "months": self.months, "label": self.label,
            "is_default": self.is_default, "available_start": self.available_start,
            "available_end": self.available_end, "available_months": self.available_months,
            "future_rows": self.future_rows, "future_latest": self.future_latest,
        }


def resolve_period(
    period: Period | None, available: list[str], current: str | None = None
) -> tuple[str | None, str | None, bool]:
    """(start, end, is_default) for a request over the months that hold money.

    Plan v10 S1.4: with nothing asked, the 12 months ending in the month of the latest
    data (fewer when the ledger holds fewer). "Latest" means the latest month with money
    that is not after `current`: one row dated a year ahead (a typo, a post-dated invoice)
    must not move the window away from the real books. Rows after it stay reachable with an
    explicit period and are counted in `LedgerPeriod.future_rows`. Only when every month is
    in the future is the latest one used, so the screen is not empty.
    """
    req = period or Period()
    is_default = req.start is None and req.end is None
    reachable = [m for m in available if current is None or m <= current] or available
    end = req.end or (reachable[-1] if reachable else None)
    if end is None:
        return None, None, is_default
    if req.start:
        return req.start, end, is_default
    start = add_months(end, 1 - DEFAULT_PERIOD_MONTHS)
    if reachable and reachable[0] <= end:
        start = max(start, reachable[0])    # no earlier than the first month of data
    return start, end, is_default


def current_month() -> str:
    """This month on the company's calendar (Europe/Istanbul)."""
    return datetime.now(istanbul()).strftime("%Y-%m")
