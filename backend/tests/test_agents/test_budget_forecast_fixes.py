"""Budget variance messages in both directions; forecast's deprecated growth_rate.

Found by SonarCloud: the message returned None for any variance <= 5, so its
"altında kaldı" branch was unreachable and a category far under budget — graded
"watch" by the severity classifier — said nothing. The forecast compared floats
to its defaults to decide whether growth_rate applied.
"""
from __future__ import annotations

from app.agents.budget_agent import _classify_variance_severity, _variance_alert_message
from app.agents.forecast_agent import _extrapolate


def test_over_budget_says_exceeded():
    msg = _variance_alert_message("rent", 12.0, 1_200_00, 10_000_00)
    assert msg is not None and "aşıldı" in msg


def test_under_budget_beyond_tolerance_says_so():
    msg = _variance_alert_message("marketing", -20.0, -2_000_00, 10_000_00)
    assert msg is not None and "altında kaldı" in msg and "%20.0" in msg
    assert _classify_variance_severity(-20.0, -2_000_00) == "watch"


def test_within_tolerance_either_way_is_silent():
    assert _variance_alert_message("rent", 4.9, 490_00, 10_000_00) is None
    assert _variance_alert_message("rent", -4.9, -490_00, 10_000_00) is None


_SERIES = [{"month": f"2026-0{m}", "in": 100_000_00, "out": 80_000_00} for m in range(1, 4)]


def test_growth_rate_sets_the_revenue_rate():
    legacy = _extrapolate(_SERIES, 3, growth_rate=1.10)
    explicit = _extrapolate(_SERIES, 3, revenue_rate=1.10, cost_rate=1.0)
    assert legacy == explicit
    assert legacy[0]["in"] == 110_000_00 and legacy[0]["out"] == 80_000_00
