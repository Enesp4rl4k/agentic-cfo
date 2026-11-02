"""Plan v8 §A3 (W6/W7) — anomalies are signal, seasonality needs two years.

Live audit 2026-10-24: three of four anomalies on the demo year were wrong
categories or routine payments, and a seasonal index was fitted to one year.

Labelled by hand from `demo/data/logo_tiger_2024.csv`:
    F101  AWS re:Invent Altyapı Genişleme   65.000  — anomaly: ~3x the monthly AWS bill
    F114  Geçici Vergi - 4. Çeyrek         210.000  — routine: quarterly prepaid tax (193)
    F007  AWS Bulut Altyapı Faturası        22.000  — routine technology bill, not a utility
    F111  Aralık Yıl Sonu Prim             120.000  — a bonus is salary, not marketing
"""
from __future__ import annotations

from pathlib import Path

from app.agents.anomaly_agent import detect_round_numbers, detect_unusual_amounts
from app.agents.data_ingestion import _tablo_ekstresi
from app.agents.forecast_agent import _detect_seasonality

DEMO = Path(__file__).resolve().parents[2] / "demo" / "data" / "logo_tiger_2024.csv"


def _demo() -> list[dict]:
    txs = _tablo_ekstresi(str(DEMO))
    assert txs
    return txs


def _row(txs: list[dict], text: str) -> dict:
    return next(t for t in txs if text in t["description"])


def test_a_bill_is_categorised_by_what_it_is_for_not_by_the_word_fatura():
    txs = _demo()
    assert _row(txs, "AWS Bulut Altyapı Faturası")["category"] == "technology"
    assert _row(txs, "Aralık Yıl Sonu Prim")["category"] == "salary"


def test_the_demo_year_flags_the_real_spike_and_none_of_the_routine_payments():
    flagged = {a["evidence"]["amount"] for a in detect_unusual_amounts(_demo())}
    assert 65_000_00 in flagged                  # F101, the genuine spike
    assert not flagged & {210_000_00, 22_000_00, 120_000_00}


def test_a_quarterly_tax_is_compared_with_its_own_account_not_monthly_kdv():
    kdv = [{"type": "expense", "category": "tax_payment", "account_code": "360",
            "amount_cents": a, "description": "KDV"} for a in (40_000_00, 42_000_00, 45_000_00,
                                                                39_000_00, 44_000_00, 41_000_00)]
    gecici = [{"type": "expense", "category": "tax_payment", "account_code": "193",
               "amount_cents": a, "description": "Geçici vergi"} for a in (85_000_00, 210_000_00)]
    assert detect_unusual_amounts(kdv + gecici) == []


def _monthly(desc: str, amount: int, months: range) -> list[dict]:
    return [{"type": "expense", "category": "rent", "amount_cents": amount,
             "description": f"{m:02d}. ay {desc}", "transaction_date": f"2024-{m:02d}-05"}
            for m in months]


def test_round_rent_and_salary_every_month_are_not_a_round_number_finding():
    txs = (_monthly("Ofis Kirası", 28_500_00, range(1, 13))
           + _monthly("Maaş Ödemesi", 145_000_00, range(1, 13)))
    assert detect_round_numbers(txs) == []


def test_round_one_off_payments_are_still_a_finding():
    payees = ["Avukat", "Noter", "Matbaa", "Fuar", "Tadilat", "Mobilya", "Kurye",
              "Danışman", "Çevirmen", "Eğitim", "Etkinlik", "Fotoğrafçı"]
    one_off = [{"type": "expense", "category": "other_expense", "amount_cents": (i + 1) * 1_000_00,
                "description": f"{p} ödemesi", "transaction_date": f"2024-{i + 1:02d}-10"}
               for i, p in enumerate(payees)]
    found = detect_round_numbers(one_off)
    assert len(found) == 1
    assert found[0]["evidence"]["round_count"] == 12


def _series(n: int) -> list[dict]:
    return [{"month": f"{2023 + i // 12}-{i % 12 + 1:02d}", "in": 100 + (50 if i % 12 == 11 else 0)}
            for i in range(n)]


def test_one_year_is_not_enough_to_call_a_month_seasonal():
    assert _detect_seasonality(_series(12)) == {}
    assert _detect_seasonality(_series(23)) == {}


def test_two_years_give_a_seasonal_index():
    idx = _detect_seasonality(_series(24))
    assert idx[12] > 1.3 > idx[6]
