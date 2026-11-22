"""A pull's window wider than the account's history is not "covered, empty months".

Review of PR #124: an open-banking pull asked for twelve months of an account opened last month stated all twelve
as complete. The eleven months before the account existed were counted as real zero months, which dilutes the
burn towards zero and the runway towards optimism. Coverage now starts at the evidence that the account existed:
the provider-reported opening date, else the first transaction received.
"""
from __future__ import annotations

from typing import Any

from app.services.coverage import annotate_series, apply_period, complete_months
from app.services.ingest.feed import Feed, pull_coverage
from app.services.pull_coverage import period_from_feed
from app.services.runway import compute_runway

OPENING = {"balance_cents": 8_000_000, "as_of": "2026-06-05", "age_days": 1, "stale": False, "filename": "e.csv"}
WINDOW = ("2025-06-01", "2026-06-30")        # twelve months and more asked for


def _extent(days: list[str], cov: dict[str, Any] | None) -> dict[str, Any]:
    period = period_from_feed({"feed": {"source": "akbank_open_banking", "pull_coverage": cov}})
    extent = apply_period({"start": min(days), "end": max(days)}, period)
    assert extent is not None
    return extent


def test_a_window_wider_than_the_history_starts_at_the_first_transaction() -> None:
    cov = pull_coverage(WINDOW, ["2026-04-01", "2026-05-14", "2026-06-20"], None)
    assert cov is not None and cov["complete"] is True
    assert (cov["covered_from"], cov["covered_until"]) == ("2026-04-01", "2026-06-30")
    assert cov["requested_from"] == "2025-06-01"          # what was ASKED stays visible; it is not what was covered


def test_the_providers_opening_date_is_evidence_that_the_account_existed() -> None:
    cov = pull_coverage(WINDOW, ["2026-04-09"], None, opened_on="2026-02-10")
    assert cov is not None and cov["covered_from"] == "2026-02-10"       # a quiet first weeks are then real quiet weeks
    cov2 = pull_coverage(("2026-03-01", "2026-03-31"), ["2026-03-09"], None, opened_on="2024-01-05")
    assert cov2 is not None and cov2["covered_from"] == "2026-03-01"      # an old account: the window as asked


def test_no_evidence_the_account_existed_states_no_coverage() -> None:
    assert pull_coverage(WINDOW, [], None) is None                         # no rows, no opening date: nothing to cover
    assert pull_coverage(WINDOW, [], None, opened_on="2026-09-01") is None   # opened after the window ended
    feed = Feed("akbank_open_banking")
    feed.window = WINDOW
    assert feed.result().feed_meta() == {"source": "akbank_open_banking", "pull_coverage": None}


def test_a_young_account_leaves_the_runway_incomputable_and_says_so() -> None:
    days = ["2026-05-02", "2026-05-20", "2026-06-05"]
    extent = _extent(days, pull_coverage(WINDOW, days, None))
    assert extent["start"] == "2026-05-02" and extent["start_stated"] is True
    months = [f"{y}-{m:02d}" for y, m in [(2025, 6), (2025, 7), (2025, 8), (2025, 9), (2025, 10), (2025, 11), (2025, 12),
                                          (2026, 1), (2026, 2), (2026, 3), (2026, 4), (2026, 5), (2026, 6)]]
    flags = complete_months([extent], months)
    # none of the empty months before the account's first transaction is "complete"; June, which the pull saw whole, is
    assert flags is not None and [m for m in months if flags[m]] == ["2026-06"]
    rows = [{"transaction_date": d, "amount_cents": 500_000, "type": "expense", "description": ""} for d in days]
    series = annotate_series([{"month": m, "in": 0, "out": 0, "net": 0} for m in months[-3:]], rows, [extent])
    block = compute_runway(OPENING, {"monthly_series": series}, "TRY")
    assert block["status"] == "insufficient_history" and block["runway_months"] is None
    assert block["months_used"] == 1 and "Üst üste 1 tam ay var" in block["message"]
    assert "en az 3 tam ay gerekir" in block["message"] and "nakit pisti hesaplanmadı" in block["message"]


def test_before_the_fix_the_same_pull_would_have_diluted_the_burn() -> None:
    """The failure this prevents: eleven stated empty months and one real one average to a tenth of the burn."""
    days = ["2026-06-02", "2026-06-20"]
    cov = pull_coverage(WINDOW, days, None)
    assert cov is not None and cov["covered_from"] > "2026-05-31"          # not "2025-06-01"
