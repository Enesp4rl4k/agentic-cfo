"""A month is complete only when the data's proven extent spans it, and the runway uses only those.

Review of PR #120: the burn was the mean of the last three calendar months that had rows, so a
statement ending on 5 June counted June as a whole month (the error is always optimistic), and
a skipped month was called "the previous one". Now a month counts only when the statement(s)
cover it from its first day to its last, and the three months must be consecutive.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.services.coverage import (
    annotate_series,
    apply_period,
    assumed_edges,
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
    def test_the_edge_tolerance_is_five_days_not_six(self) -> None:
        months = ["2026-02", "2026-03", "2026-04"]
        full = dict.fromkeys(months, True)
        assert complete_months([{"start": "2026-02-01", "end": "2026-04-30"}], months) == full
        # Start edge: 5 days with no transaction (first one on the 6th) is tolerated, 6 (the 7th) is not.
        assert complete_months([{"start": "2026-02-06", "end": "2026-04-30"}], months) == full
        assert complete_months([{"start": "2026-02-07", "end": "2026-04-30"}], months)["2026-02"] is False
        # End edge: the last transaction 5 days before the month's last day is tolerated, 6 days is not.
        assert complete_months([{"start": "2026-02-01", "end": "2026-04-25"}], months) == full
        assert complete_months([{"start": "2026-02-01", "end": "2026-04-24"}], months)["2026-04"] is False

    def test_the_end_tolerance_never_completes_a_month_that_has_not_ended(self) -> None:
        # A statement ending on the 25th, read on the 27th: the 26th-30th have not happened, they are not quiet days.
        extent = [{"start": "2026-09-01", "end": "2026-11-25"}]
        months = ["2026-09", "2026-10", "2026-11"]
        assert complete_months(extent, months, date(2026, 11, 27))["2026-11"] is False
        assert complete_months(extent, months, date(2026, 11, 30))["2026-11"] is False  # the last day is not over
        assert complete_months(extent, months, date(2026, 12, 1)) == dict.fromkeys(months, True)
        assert assumed_edges(extent, "2026-11", date(2026, 11, 27)) == []
        assert assumed_edges(extent, "2026-11", date(2026, 12, 1)) == [{"edge": "end", "days": 5}]
        # Leap February and the year end: the same rule at both boundaries.
        feb = [{"start": "2028-02-01", "end": "2028-02-24"}]
        assert complete_months(feb, ["2028-02"], date(2028, 2, 29)) == {"2028-02": False}
        assert complete_months(feb, ["2028-02"], date(2028, 3, 1)) == {"2028-02": True}
        dec = [{"start": "2026-12-01", "end": "2026-12-27"}]
        assert complete_months(dec, ["2026-12"], date(2026, 12, 31)) == {"2026-12": False}
        assert complete_months(dec, ["2026-12"], date(2027, 1, 1)) == {"2026-12": True}
        # A statement that reaches the month's last day is complete on that day already: nothing was assumed.
        assert complete_months([{"start": "2026-11-01", "end": "2026-11-30"}], ["2026-11"], date(2026, 11, 30)) == {"2026-11": True}

    def test_the_journeys_burn_does_not_change_in_the_last_days_of_the_month(self) -> None:
        # The browser journey's ordinary quarter, its last row on 25 November (CI 2026-11-27 00:10 UTC): November
        # (five days short) counted as whole before the month was over, and the burn read -13.833,33, not -5.333,33.
        rows = [
            _row("2026-08-02", 1_200_000), _row("2026-08-12", 5_000_000, "income"), _row("2026-09-02", 1_200_000),
            _row("2026-09-20", 3_000_000), _row("2026-10-02", 1_200_000), _row("2026-11-25", 1_250_000, "income"),
        ]
        extents = [{"start": "2026-08-02", "end": "2026-11-25"}]
        months: dict[str, dict[str, int]] = {}
        for r in rows:
            b = months.setdefault(r["transaction_date"][:7], {"in": 0, "out": 0})
            b["in" if r["type"] == "income" else "out"] += r["amount_cents"]
        base = [{"month": k, "in": v["in"], "out": v["out"], "net": v["in"] - v["out"]} for k, v in sorted(months.items())]
        opening = {**OPENING, "balance_cents": 11_650_000, "as_of": "2026-11-25"}
        for today in (date(2026, 11, 26), date(2026, 11, 27), date(2026, 11, 30)):
            block = compute_runway(opening, {"monthly_series": annotate_series(base, rows, extents, today)}, "TRY")
            assert [m["month"] for m in block["months"]] == ["2026-08", "2026-09", "2026-10"], today
            assert block["avg_monthly_net_cents"] == -533_333 and block["runway_months"] == 21.8, today

    def test_a_stated_period_needs_no_tolerance_and_a_short_one_gets_none(self) -> None:
        months = ["2026-02", "2026-03"]
        stated = {"start": "2026-02-01", "end": "2026-03-31", "start_stated": True, "end_stated": True}
        assert complete_months([stated], months) == dict.fromkeys(months, True)
        assert assumed_edges([stated], "2026-02") == []
        # The tolerance is for files that state nothing: a stated end of the 29th is the period.
        assert complete_months([{**stated, "end": "2026-03-29"}], months)["2026-03"] is False

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
        assert extents_for({"transactions": rows}) == [{"start": "2026-02-03", "end": "2026-02-20", "start_stated": False, "end_stated": False}]
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


class TestEvidenceOrder:
    def test_a_realistic_three_month_statement_gets_a_runway_with_the_assumption_stated(self) -> None:
        # January 2 to March 30: one day short at each end, which weekends explain.
        rows = [
            _row("2026-01-02", 3_000_000), _row("2026-01-20", 3_000_000), _row("2026-02-02", 3_000_000),
            _row("2026-02-20", 3_000_000), _row("2026-03-02", 3_000_000), _row("2026-03-30", 3_000_000),
        ]
        block = _runway(rows, [{"start": "2026-01-02", "end": "2026-03-30"}])
        assert block["status"] == "computed" and block["basis"] == "assumed"
        assert "Ocak ayının ilk 1 günü ve Mart ayının son 1 günü için işlem yok; ay tam sayıldı (varsayım)" in block["message"]
        assert block["months_used"] == 3 and block["level"] is not None  # may be critical, with the assumption said

    def test_a_stated_period_makes_the_same_statement_known(self) -> None:
        # First row on the 3rd, last on the 29th: the header (1 Jan - 31 Mar) explains the quiet days.
        rows = [_row("2026-01-03", 3_000_000), _row("2026-02-20", 3_000_000), _row("2026-03-29", 3_000_000)]
        extent = apply_period({"start": "2026-01-03", "end": "2026-03-29"}, {"start": "2026-01-01", "end": "2026-03-31"}, "e.csv")
        block = _runway(rows, [extent or {}])
        assert block["status"] == "computed" and block["basis"] == "known" and block["assumptions"] == []
        assert "varsayım" not in block["message"]

    def test_a_stated_period_the_rows_do_not_fit_in_is_not_used(self) -> None:
        out = apply_period({"start": "2026-01-02", "end": "2026-04-10"}, {"start": "2026-01-01", "end": "2026-03-31"})
        assert out is not None and out["end_stated"] is False and out["end"] == "2026-04-10"

    def test_two_chained_statements_complete_the_months_around_the_join_without_assumption(self) -> None:
        a = {"start": "2026-01-01", "end": "2026-02-20", "opening_cents": 0, "closing_cents": 500}
        b = {"start": "2026-02-25", "end": "2026-03-31", "opening_cents": 500, "closing_cents": 900}
        months = ["2026-01", "2026-02", "2026-03"]
        assert complete_months([a, b], months) == dict.fromkeys(months, True)
        assert all(assumed_edges([a, b], m) == [] for m in months)

    def test_a_first_transaction_on_the_7th_leaves_the_month_out_and_names_it(self) -> None:
        rows = [
            _row("2026-01-07", 3_000_000), _row("2026-02-02", 3_000_000), _row("2026-03-02", 3_000_000),
            _row("2026-04-02", 3_000_000), _row("2026-05-12", 3_000_000),
        ]
        block = _runway(rows, [{"start": "2026-01-07", "end": "2026-05-12"}])
        assert [m["month"] for m in block["months"]] == ["2026-02", "2026-03", "2026-04"]
        assert "Ocak yalnızca 7–31 arası var; hesaba katılmadı" in block["message"]

    def test_the_short_account_is_named_by_its_file(self) -> None:
        bank_a = {"start": "2026-01-01", "end": "2026-06-30", "opening_cents": 0, "closing_cents": 100, "filename": "a-bank.csv"}
        bank_b = {"start": "2026-03-01", "end": "2026-06-30", "opening_cents": 5, "closing_cents": 7, "filename": "ikinci-banka.csv"}
        rows = [_row(f"2026-0{m}-10", 3_000_000) for m in range(1, 7)]
        block = _runway(rows, [bank_a, bank_b])
        assert "ikinci-banka.csv ekstresi 1 Mart 2026 – 30 Haziran 2026 arasını kapsıyor; Ocak, Şubat bu hesap için eksik" in block["message"]
        assert "a-bank.csv" not in block["message"]


class TestAHeaderIsCheckedAgainstTheRows:
    PERIOD = {"start": "2025-12-01", "end": "2026-03-31"}

    def test_a_truncated_export_does_not_make_the_missing_days_known(self) -> None:
        # Header: 1 December to 31 March. Rows stop on 10 March: 21 quiet days is not "a few".
        rows = [
            _row("2025-12-02", 3_000_000), _row("2026-01-05", 3_000_000), _row("2026-02-05", 3_000_000),
            _row("2026-03-10", 3_000_000),
        ]
        extent = apply_period({"start": "2025-12-02", "end": "2026-03-10"}, self.PERIOD, "kesik.csv")
        assert extent is not None and extent["end_stated"] is False and extent["end"] == "2026-03-10"
        assert extent["mismatch"] == [{"edge": "end", "stated": "2026-03-31", "actual": "2026-03-10"}]
        block = _runway(rows, [extent])
        assert [m["month"] for m in block["months"]] == ["2025-12", "2026-01", "2026-02"]
        assert block["basis"] == "known"  # December's start edge agrees with the header; March is out
        assert "Mart yalnızca 1–10 arası var; hesaba katılmadı" in block["message"]
        assert "Ekstre başlığındaki bitiş tarihi 31 Mart 2026, satırların son tarihi 10 Mart 2026: başlığa güvenilmedi" in block["message"]

    def test_a_header_that_agrees_within_the_tolerance_makes_the_edges_known(self) -> None:
        rows = [
            _row("2025-12-04", 3_000_000), _row("2026-01-05", 3_000_000), _row("2026-02-05", 3_000_000),
            _row("2026-03-28", 3_000_000),
        ]
        extent = apply_period({"start": "2025-12-04", "end": "2026-03-28"}, self.PERIOD, "e.csv")
        assert extent is not None and extent["start_stated"] and extent["end_stated"] and "mismatch" not in extent
        assert (extent["start"], extent["end"]) == ("2025-12-01", "2026-03-31")
        block = _runway(rows, [extent])
        assert block["status"] == "computed" and block["basis"] == "known" and block["months_used"] == 3
        assert "varsayım" not in block["message"] and "güvenilmedi" not in block["message"]

    def test_a_header_start_the_rows_do_not_match_falls_back_for_that_edge(self) -> None:
        # Header start 1 December; the first row is 20 December: December is not whole, and it is said.
        rows = [
            _row("2025-12-20", 3_000_000), _row("2026-01-05", 3_000_000), _row("2026-02-05", 3_000_000),
            _row("2026-03-05", 3_000_000), _row("2026-03-30", 3_000_000),
        ]
        extent = apply_period({"start": "2025-12-20", "end": "2026-03-30"}, self.PERIOD, "e.csv")
        assert extent is not None and extent["start_stated"] is False and extent["end_stated"] is True
        assert extent["start"] == "2025-12-20"
        block = _runway(rows, [extent])
        assert [m["month"] for m in block["months"]] == ["2026-01", "2026-02", "2026-03"]
        assert "Aralık yalnızca 20–31 arası var; hesaba katılmadı" in block["message"]
        assert "Ekstre başlığındaki başlangıç tarihi 1 Aralık 2025, satırların ilk tarihi 20 Aralık 2025: başlığa güvenilmedi" in block["message"]
