"""Which radar week a payment falls in, pinned at the boundaries.

The calendar disables "1 hafta öne al" for a payment in week 1, so which payments are in week 1 decides
which buttons work. It depends on the day the radar is computed: rent projected on the 2nd is in week 1
from the 26th to the 2nd. The browser journey once broke on exactly that; this pins the rule itself.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.services.cash_radar import week_index
from app.services.recurring_obligations import RecurringObligation, project_recurring_obligations


@pytest.mark.parametrize(
    ("offset", "week"),
    [(0, 0), (1, 0), (6, 0), (7, 1), (8, 1), (13, 1), (14, 2), (90, 12)],
)
def test_week_boundaries_are_anchor_through_anchor_plus_six(offset: int, week: int) -> None:
    anchor = date(2026, 11, 26)
    assert week_index(anchor + timedelta(days=offset), anchor) == week


def test_week_index_across_a_month_end() -> None:
    anchor = date(2026, 11, 30)
    assert week_index(date(2026, 12, 6), anchor) == 0  # anchor + 6
    assert week_index(date(2026, 12, 7), anchor) == 1  # anchor + 7


def test_a_day_before_the_anchor_is_not_in_any_week() -> None:
    assert week_index(date(2026, 11, 25), date(2026, 11, 26)) < 0


def _rent_week(today: date) -> int:
    rent = RecurringObligation(
        key="ofis-kirasi",
        label="Ofis kirası",
        counterparty="Ofis kirası",
        amount_cents=1_200_000,
        day_of_month=2,
        observed_months_count=3,
        source_row_ids=[],
        last_seen=date(2026, 11, 2),
    )
    nearest = min(project_recurring_obligations([rent], today), key=lambda p: p.expected_date)
    return week_index(nearest.expected_date, today)


@pytest.mark.parametrize(
    ("today", "week"),
    [
        (date(2026, 11, 24), 1),  # the 2nd is 8 days away: week 2 (index 1)
        (date(2026, 11, 25), 1),  # 7 days away
        (date(2026, 11, 26), 0),  # 6 days away: week 1, so "öne al" is disabled for the rent
        (date(2026, 11, 30), 0),  # month end
        (date(2026, 12, 1), 0),
        (date(2026, 12, 2), 0),  # due today
        (date(2026, 12, 3), 4),  # just missed it: next month's 2nd, 30 days away
    ],
)
def test_rent_projected_on_the_second_is_in_week_one_only_from_the_26th(
    today: date, week: int
) -> None:
    assert _rent_week(today) == week
