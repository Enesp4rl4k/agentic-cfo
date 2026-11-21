"""A month is complete only when the data's proven extent spans it, and the runway uses only those.

Review of PR #120: the burn was the mean of the last three calendar months that had rows, so a
statement ending on 5 June counted June as a whole month (the error is always optimistic), and
a skipped month was called "the previous one". Now a month counts only when the statement(s)
cover it from its first day to its last, and the three months must be consecutive.
"""
from __future__ import annotations

from typing import Any

from app.services.coverage import (
    annotate_series,
    complete_months,
    extents_for,
    gaps,
    usable_months,
)
from app.services.runway import compute_runway

OPENING = {"balance_cents": 8_000_000, "as_of": "2026-06-05", "age_days": 1, "stale": False, "filename": "e.csv"}


def _row(day: str, cents: int, kind: str = "expense", description: str = "") -> dict[str, Any]:
    return {"transaction_date": day, "amount_cents": cents, "type": kind, "description": description}


def _series(rows: list[dict[str, Any]], extents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    months: dict[str, dict[str, int]] = {}
    for r in rows:
        b = months.setdefault(r["transaction_date"][:7], {"in": 0, "out": 0})
        b["in" if r["type"] == "income" else "out"] += r["amount_cents"]
    base = [{"month": k, "in": v["in"], "out": v["out"], "net": v["in"] - v["out"]} for k, v in sorted(months.items())]
    return annotate_series(base, rows, extents)


def _runway(rows: list[dict[str, Any]], extents: list[dict[str, Any]], opening: dict[str, Any] = OPENING) -> dict[str, Any]:
    return compute_runway(opening, {"monthly_series": _series(rows, extents)}, "TRY")


class TestReviewersCases:
    def test_a_statement_ending_on_the_5th_does_not_make_june_a_month(self) -> None:
        # Mar, Apr, May -30.000 each; June 1-5 -5.000. The old burn was the mean of Apr, May, Jun (21.7k).
        rows = [_row("2026-03-02", 3_000_000), _row("2026-04-10", 3_000_000), _row("2026-05-12", 3_000_000), _row("2026-06-05", 500_000)]
        block = _runway(rows, [{"start": "2026-03-01", "end": "2026-06-05"}])
        assert block["status"] == "computed"
        assert block["avg_monthly_net_cents"] == -3_000_000  # not -2_166_667
        assert block["runway_months"] == 2.7 and block["level"] == "critical"  # 80.000 / 30.000, not ~3,7 (warning)
        assert "Haziran yalnızca 1–5 arası var; hesaba katılmadı" in block["message"]
        assert "Mart -₺30.000,00, Nisan -₺30.000,00, Mayıs -₺30.000,00" in block["message"]

    def test_the_exact_case_has_only_two_complete_months_and_says_so(self) -> None:
        rows = [_row("2026-04-02", 3_000_000), _row("2026-05-02", 3_000_000), _row("2026-06-05", 500_000)]
        block = _runway(rows, [{"start": "2026-04-01", "end": "2026-06-05"}])
        assert block["status"] == "insufficient_history" and block["runway_months"] is None
        assert block["months_used"] == 2
        assert "Üst üste 2 tam ay var" in block["message"] and "Haziran yalnızca 1–5 arası" in block["message"]

    def test_a_gap_month_is_never_called_the_previous_one(self) -> None:
        series = [
            {"month": m, "in": 0, "out": 3_000_000, "net": -3_000_000, "complete": True}
            for m in ("2026-01", "2026-02", "2026-05", "2026-06")
        ]
        assert gaps(series) == [("2026-03", "2026-04")]
        block = compute_runway(OPENING, {"monthly_series": series}, "TRY")
        assert block["status"] == "insufficient_history" and block["months_used"] == 2
        assert "Mart–Nisan verisi yok" in block["message"] and "son 3 ay" not in block["message"]

    def test_three_consecutive_months_after_a_gap_are_used(self) -> None:
        series = [
            {"month": m, "in": 0, "out": 3_000_000, "net": -3_000_000, "complete": True}
            for m in ("2026-01", "2026-02", "2026-05", "2026-06", "2026-07")
        ]
        block = compute_runway(OPENING, {"monthly_series": series}, "TRY")
        assert block["status"] == "computed" and [m["month"] for m in block["months"]] == ["2026-05", "2026-06", "2026-07"]


class TestWhichMonthsAreComplete:
    def test_first_and_last_month_need_their_first_and_last_day(self) -> None:
        months = ["2026-02", "2026-03", "2026-04"]
        assert complete_months([{"start": "2026-02-01", "end": "2026-04-30"}], months) == dict.fromkeys(months, True)
        assert complete_months([{"start": "2026-02-07", "end": "2026-04-30"}], months) == {"2026-02": False, "2026-03": True, "2026-04": True}
        assert complete_months([{"start": "2026-02-01", "end": "2026-04-29"}], months) == {"2026-02": True, "2026-03": True, "2026-04": False}

    def test_no_extent_at_all_is_unknown_not_complete(self) -> None:
        assert complete_months([], ["2026-01"]) is None
        series = [{"month": f"2026-0{i}", "in": 0, "out": 1, "net": -1} for i in (1, 2, 3)]
        out = annotate_series(series, [], [])
        assert all(m["complete"] is None for m in out)
        assert compute_runway(OPENING, {"monthly_series": out}, "TRY")["status"] == "coverage_unknown"

    def test_a_covered_month_without_rows_is_a_real_zero_month(self) -> None:
        rows = [_row("2026-01-10", 100), _row("2026-03-10", 100)]
        out = _series(rows, [{"start": "2026-01-01", "end": "2026-03-31"}])
        feb = next(m for m in out if m["month"] == "2026-02")
        assert feb["net"] == 0 and feb["complete"] is True
        assert [m["month"] for m in usable_months(out)] == ["2026-01", "2026-02", "2026-03"]

    def test_a_month_nothing_covers_is_missing_not_zero(self) -> None:
        rows = [_row("2026-01-10", 100), _row("2026-03-10", 100)]
        extents = [{"start": "2026-01-01", "end": "2026-01-31"}, {"start": "2026-03-01", "end": "2026-03-31"}]
        out = _series(rows, extents)
        assert [m["month"] for m in out] == ["2026-01", "2026-03"]  # no February entry
        assert gaps(out) == [("2026-02", "2026-02")]

    def test_two_banks_covering_different_ranges_need_both(self) -> None:
        bank_a = {"start": "2026-01-01", "end": "2026-06-30", "opening_cents": 0, "closing_cents": 100}
        bank_b = {"start": "2026-03-01", "end": "2026-06-30", "opening_cents": 5, "closing_cents": 7}
        flags = complete_months([bank_a, bank_b], ["2026-01", "2026-02", "2026-03", "2026-06"])
        assert flags == {"2026-01": False, "2026-02": False, "2026-03": True, "2026-06": True}

    def test_one_accounts_consecutive_statements_join(self) -> None:
        jan = {"start": "2026-01-01", "end": "2026-01-31", "opening_cents": 0, "closing_cents": 500}
        feb = {"start": "2026-02-01", "end": "2026-02-28", "opening_cents": 500, "closing_cents": 900}
        other = {"start": "2026-02-01", "end": "2026-02-28", "opening_cents": 1, "closing_cents": 9}
        assert complete_months([jan, feb], ["2026-01", "2026-02"]) == {"2026-01": True, "2026-02": True}
        # A statement that does not open on the balance the first closed on is another account.
        assert complete_months([jan, other], ["2026-01", "2026-02"]) == {"2026-01": False, "2026-02": False}

    def test_a_file_run_uses_its_own_extent_and_a_ledger_run_every_statement(self) -> None:
        rows = [_row("2026-02-03", 1), _row("2026-02-20", 1)]
        assert extents_for({"transactions": rows}) == [{"start": "2026-02-03", "end": "2026-02-20"}]
        stored = [{"start": "2026-01-01", "end": "2026-03-31"}]
        assert extents_for({"transactions": rows, "ledger_view": {}, "statement_extents": stored}) == stored


class TestWhatTheMessageSays:
    def test_balance_later_than_the_last_complete_month_is_said(self) -> None:
        rows = [_row("2026-01-05", 3_000_000), _row("2026-02-05", 3_000_000), _row("2026-03-05", 3_000_000)]
        block = _runway(rows, [{"start": "2026-01-01", "end": "2026-03-31"}], {**OPENING, "as_of": "2026-05-20"})
        assert "Bakiye 20 Mayıs 2026 tarihli, son tam ay Mart" in block["message"]
        assert "hesaba katılmadı" not in block["message"]  # no partial month; the balance note is the one

    def test_a_one_off_over_half_of_the_outflow_is_named_without_adjusting_it(self) -> None:
        rows = [
            _row("2026-01-05", 1_000_000), _row("2026-02-05", 1_000_000),
            _row("2026-03-05", 9_000_000, description="Makine alımı"),
        ]
        block = _runway(rows, [{"start": "2026-01-01", "end": "2026-03-31"}])
        assert "Makine alımı" in block["message"] and "5 Mart 2026" in block["message"]
        assert "yarısından fazlası" in block["message"]
        assert block["avg_monthly_net_cents"] == -(11_000_000 // 3)  # as it is, no adjustment

    def test_an_even_spread_has_no_one_off_note(self) -> None:
        rows = [_row("2026-01-05", 3_000_000), _row("2026-02-05", 3_000_000), _row("2026-03-05", 3_000_000)]
        assert "Not:" not in _runway(rows, [{"start": "2026-01-01", "end": "2026-03-31"}])["message"]

    def test_a_correction_pair_is_no_one_off_and_nets_out(self) -> None:
        rows = [
            _row("2026-01-05", 1_000_000), _row("2026-02-05", 1_000_000), _row("2026-03-05", 1_000_000),
            _row("2026-02-10", 9_000_000, description="Yanlış kayıt"),
            _row("2026-02-11", 9_000_000, kind="income", description="Yanlış kaydın düzeltmesi"),
        ]
        block = _runway(rows, [{"start": "2026-01-01", "end": "2026-03-31"}])
        assert "Yanlış kayıt" not in block["message"] and "Not:" not in block["message"]
        assert block["avg_monthly_net_cents"] == -1_000_000

    def test_a_negative_balance_does_not_claim_the_cash_lasts(self) -> None:
        rows = [_row("2026-01-05", 3_000_000), _row("2026-02-05", 3_000_000), _row("2026-03-05", 3_000_000)]
        block = _runway(rows, [{"start": "2026-01-01", "end": "2026-03-31"}], {**OPENING, "balance_cents": -500_000})
        assert "nakit bitmiş" in block["message"] and "yeter" not in block["message"]
        assert block["level"] == "critical" and block["runway_months"] == 0.0
