"""A check that passes under both hypotheses is not evidence for either.

Review of #126 (round 2): an all-ambiguous daily-balance statement (every segment sums to zero) reconciles under BOTH
sign conventions and was booked by plain sign with no question. Verifying a sign convention must be DISCRIMINATING:
both conventions are tried in every row order the dates allow; it is proven only if exactly the convention read fits
and at least two reconciling segments tell the conventions apart (signed sum not zero). One such segment is weak
(asked, the suggestion pre-selected); none, or both conventions fitting, is ambiguous (asked).
"""
from __future__ import annotations

import random
from typing import Any

import pytest

from app.parsers.balance_chain import BOTH_ORDERS, convention_proof, date_orders
from app.services.ingest.rows import _try_parse_csv

NL = "\n"
HEADER = "Tarih;Açıklama;Tutar;Bakiye;Para Birimi"


def _csv(*rows: str) -> str:
    return NL.join([HEADER, *rows]) + NL


def _pairs(spec: list[tuple[int, int]], start: int = 5_000) -> str:
    """Daily rows: `+a` (no balance) then `-b` carrying the balance; one pair per day, dates ascending."""
    rows, balance = [], start
    for day, (a, b) in enumerate(spec, 1):
        rows.append(f"{day:02d}.03.2026;Giriş {day};{a},00;;TRY")
        balance += a - b
        rows.append(f"{day:02d}.03.2026;Çıkış {day};-{b},00;{balance},00;TRY")
    return _csv(*rows)


def _placed(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in rows if r["type"] in ("income", "expense")]


def _asked(rows: list[dict[str, Any]], reason: str = "sign_unconfirmed") -> dict[str, Any]:
    assert not _placed(rows), "nothing may be booked"
    assert {r["direction_file"]["reason"] for r in rows} == {reason}
    return next((r["direction_question"] for r in rows if "direction_question" in r), {})


# ── the reviewer's files ─────────────────────────────────────────────────────────────────────────────────────

def test_the_reviewers_all_zero_sum_file_is_asked_and_nothing_is_booked() -> None:
    rows = _try_parse_csv(_pairs([(100, 100)] * 7)) or []            # 14 rows: +100 (no balance), -100 with 5.000,00
    assert len(rows) == 14
    assert "suggested" not in _asked(rows)                          # both conventions fit: nothing to suggest


def test_six_zero_sum_segments_and_one_informative_one_is_weak_asked_with_the_suggestion() -> None:
    rows = _try_parse_csv(_pairs([(100, 100)] * 7 + [(300, 100)])) or []
    q = _asked(rows)
    assert q["suggested"] == {"answer": "sign_correct", "reason": "single_step"}
    assert "ayırt etmeye yetmiyor" in q["note"]


def test_two_discriminating_segments_prove_the_convention_and_book_without_a_question() -> None:
    rows = _try_parse_csv(_pairs([(100, 100)] * 6 + [(300, 100), (250, 50)])) or []
    assert not any("direction_file" in r for r in rows)
    placed = _placed(rows)
    assert len(placed) == 15 and {r["description"] for r in rows if r.get("outside_chain")} == {"Giriş 1"}
    assert all((r["type"] == "income") == r["description"].startswith("Giriş") for r in placed)


def _periodic(dated: bool) -> str:
    """Every day +300 then -100, the balance FALLING 200 a day: only plus = out explains it, in the order the dates give."""
    rows, balance = [], 10_000
    for day in range(1, 8):
        balance -= 200
        when = f"{day:02d}.03.2026" if dated else "01.03.2026"
        rows += [f"{when};Hareket A{day};300,00;;TRY", f"{when};Hareket B{day};-100,00;{balance},00;TRY"]
    return _csv(*rows)


def test_the_periodic_file_with_dates_is_held_as_a_contradiction_never_booked_plain() -> None:
    # the dates fix the order (oldest first): the plain signs (+300 in, -100 out) would RAISE the balance, it falls
    rows = _try_parse_csv(_periodic(dated=True)) or []
    _asked(rows, "balance_contradicts")


def test_the_periodic_file_without_usable_dates_is_ambiguous_and_asked() -> None:
    rows = _try_parse_csv(_periodic(dated=False)) or []              # one date: either order, either convention can fit
    assert not _placed(rows) and rows and all("direction_file" in r for r in rows)


# ── the proof itself ─────────────────────────────────────────────────────────────────────────────────────────

def test_convention_proof_names_its_four_outcomes() -> None:
    inc, exp = "income", "expense"
    zero = ([100, 100, 100, 100], [inc, exp, inc, exp], [None, 5000, None, 5000])
    assert convention_proof(*zero) == "ambiguous"
    one = ([100, 100, 300, 100], [inc, exp, inc, exp], [None, 5000, None, 5200])
    assert convention_proof(*one, orders=(False,)) == "weak"
    two = ([100, 100, 300, 100, 250, 50], [inc, exp, inc, exp, inc, exp], [None, 5000, None, 5200, None, 5400])
    assert convention_proof(*two, orders=(False,)) == "proven"
    # without dates the SAME rows read newest-first fit the flipped convention: an unfixed order proves nothing
    assert convention_proof(*one) == "ambiguous"
    wrong = ([100, 100, 300, 100, 250, 50], [exp, inc, exp, inc, exp, inc], [None, 5000, None, 5200, None, 5400])
    assert convention_proof(*wrong, orders=(False,)) == "no"                         # as read it does not fit (the flipped reading does)


def test_dates_fix_the_row_order_when_they_decide_it() -> None:
    assert date_orders(["01.03.2026", "02.03.2026", "02.03.2026", "09.03.2026"]) == (False,)
    assert date_orders(["09.03.2026", "08.03.2026", "08.03.2026"]) == (True,)
    assert date_orders(["01.03.2026", "01.03.2026"]) == BOTH_ORDERS
    assert date_orders(["01.03.2026", "05.03.2026", "02.03.2026"]) == BOTH_ORDERS and date_orders([None, "bozuk"]) == BOTH_ORDERS


def test_a_single_balance_step_is_not_a_proof_in_an_ordinary_every_row_chain() -> None:
    two_rows = _csv("01.03.2026;Satış;100,00;1.100,00;TRY", "02.03.2026;Kira;-40,00;1.060,00;TRY")
    assert not _placed(_try_parse_csv(two_rows) or [])               # one step: weak, asked
    three_rows = _csv("01.03.2026;Satış;100,00;1.100,00;TRY", "02.03.2026;Kira;-40,00;1.060,00;TRY",
                      "03.03.2026;Gaz;-10,00;1.050,00;TRY")
    assert [r["type"] for r in _try_parse_csv(three_rows) or []] == ["income", "expense", "expense"]


# ── known fixtures still book question-free ──────────────────────────────────────────────────────────────────

def test_the_e2e_statements_still_book_without_a_question() -> None:
    bank = _csv(
        '01.09.2026;Ofis kirası;"-12.000,00";"108.000,00";TRY', '12.09.2026;Satış tahsilatı;"50.000,00";"158.000,00";TRY',
        '02.10.2026;Ofis kirası;"-12.000,00";"146.000,00";TRY', '20.10.2026;Personel maaş;"-30.000,00";"116.000,00";TRY',
        '02.11.2026;Ofis kirası;"-12.000,00";"104.000,00";TRY', '19.11.2026;Danışmanlık;"12.500,00";"116.500,00";TRY')
    short = _csv(
        '02.09.2026;Satış;"20.000,00";"120.000,00";TRY', '03.09.2026;Kira;"-10.000,00";"110.000,00";TRY',
        '04.09.2026;Maaş;"-40.000,00";"70.000,00";TRY', '02.10.2026;Satış;"20.000,00";"90.000,00";TRY',
        '03.10.2026;Kira;"-10.000,00";"80.000,00";TRY', '04.10.2026;Maaş;"-40.000,00";"40.000,00";TRY')
    for text in (bank, short):
        rows = _try_parse_csv(text) or []
        assert len(_placed(rows)) == 6 and not any("direction_file" in r for r in rows)


GARANTI_8 = (
    "GARANTİ BBVA\n"
    "01.02.2026  MAAŞ ÖDEMESİ  -1.000,00  9.000,00\n02.02.2026  EFT GELEN  2.000,00  11.000,00\n"
    "03.02.2026  FATURA  -500,00  10.500,00\n04.02.2026  KİRA  -3.000,00  7.500,00\n"
    "05.02.2026  TAHSİLAT  4.000,00  11.500,00\n06.02.2026  SU  -100,00  11.400,00\n"
    "07.02.2026  HAVALE GELEN  600,00  12.000,00\n08.02.2026  ELEKTRİK  -250,00  11.750,00\n"
)


def test_the_garanti_eight_line_statement_is_still_verified_and_question_free() -> None:
    from app.parsers.banks.garanti import GarantiParser
    from app.services.ingest.door import read_text_statement

    door = read_text_statement(GarantiParser(), GARANTI_8, "garanti.txt")
    assert door.ledger.balance_check == "verified" and len(door.rows) == 8
    assert all(r["type"] in ("income", "expense") and "direction_file" not in r for r in door.rows)


# ── property: a random daily-balance file is read as its own convention, or asked, never the opposite ─────────

@pytest.mark.parametrize("seed", range(80))
def test_a_random_daily_balance_file_is_never_booked_as_the_opposite_convention(seed: int) -> None:
    rng = random.Random(seed)
    plus_in = rng.random() < 0.5
    every = rng.randint(1, 4)                                       # a balance on every n-th row
    dated = rng.random() < 0.7
    truth: list[str] = []
    lines: list[str] = []
    balance = rng.randint(1_000, 9_000)
    for i in range(rng.randint(8, 30)):
        kind = rng.choice(("income", "expense"))
        mag = rng.choice((100, 100, 250, rng.randint(1, 900)))      # repeated magnitudes make zero-sum segments likely
        balance += mag if kind == "income" else -mag
        written = mag if (kind == "income") == plus_in else -mag
        shown = f"{balance},00" if i % every == every - 1 else ""
        day = f"{1 + i // 2:02d}.03.2026" if dated else "01.03.2026"
        lines.append(f"{day};Hareket {i};{written},00;{shown};TRY")
        truth.append(kind)
    rows = _try_parse_csv(_csv(*lines)) or []
    assert len(rows) == len(truth)
    for row, expected in zip(rows, truth, strict=True):
        assert row["type"] in (None, expected), (seed, row["description"], row["type"], expected)
