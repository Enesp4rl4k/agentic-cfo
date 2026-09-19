"""Anomaly detection over a real-sized statement: same findings, linear time.

The per-row statistics recomputed the whole category for every row. A 6,000-row
bank statement held the event loop — and so every request to the API — for
over a minute. These tests pin the results to the textbook definitions and the
cost to something a request can wait behind.
"""
from __future__ import annotations

import random
import statistics
import time

import pytest

from app.agents.anomaly_agent import (
    DUPLICATE_WINDOW_DAYS,
    IQR_MULTIPLIER,
    Z_SCORE_THRESHOLD,
    _days_between,
    detect_duplicates,
    detect_unusual_amounts,
)


def _percentile(xs: list[float], q: float) -> float:
    s = sorted(xs)
    pos = (len(s) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def _reference_unusual(txs):
    """Row by row, straight from the definitions."""
    out = []
    cats: dict[str, list] = {}
    for t in txs:
        if t.get("type") == "expense":
            cats.setdefault(t.get("category", "other_expense"), []).append(t)
    for rows in cats.values():
        amounts = [float(t["amount_cents"]) for t in rows]
        if len(amounts) < 5:
            continue
        mean, std = statistics.mean(amounts), statistics.stdev(amounts)
        q1, q3 = _percentile(amounts, 0.25), _percentile(amounts, 0.75)
        for t, a in zip(rows, amounts):
            z = (a - mean) / std if std else 0.0
            iqr = (a - q3) / (q3 - q1) if q3 != q1 else 0.0
            if abs(z) > Z_SCORE_THRESHOLD and iqr > IQR_MULTIPLIER:
                out.append((t["id"], round(z, 2), round(iqr, 2)))
    return out


def _reference_duplicates(txs):
    out, seen = [], []
    for t in (t for t in txs if t.get("type") == "expense"):
        vendor = (t.get("vendor") or "").lower().strip()
        for prev in seen:
            if (prev.get("amount_cents") == t.get("amount_cents", 0)
                    and (prev.get("vendor") or "").lower().strip() == vendor and vendor):
                days = _days_between(t.get("transaction_date"), prev.get("transaction_date"))
                if days is not None and days <= DUPLICATE_WINDOW_DAYS:
                    out.append((t["id"], prev["id"]))
                    break
        seen.append(t)
    return out


def _statement(n: int, seed: int) -> list[dict]:
    rnd = random.Random(seed)
    rows = []
    for i in range(n):
        amount = rnd.choice([100_000, 250_000]) if rnd.random() < 0.3 else rnd.randint(1, 10**7)
        if rnd.random() < 0.02:
            amount *= 50
        rows.append({
            "id": f"t{i}", "type": rnd.choice(["expense", "expense", "income"]),
            "category": rnd.choice(["rent", "payroll", "software", "tiny"]) if n > 20 else "rent",
            "amount_cents": amount, "vendor": rnd.choice(["", "Acme", "acme ", "Beta", None]),
            "transaction_date": f"2024-0{rnd.randint(1, 3)}-{rnd.randint(10, 28)}",
        })
    return rows


@pytest.mark.parametrize("seed", range(8))
def test_findings_match_the_definitions(seed):
    txs = _statement(random.Random(seed).choice([6, 40, 400]), seed)
    got = [(a["transaction_ids"][0], a["evidence"]["z_score"], a["evidence"]["iqr_score"])
           for a in detect_unusual_amounts(txs)]
    assert got == _reference_unusual(txs)
    assert [tuple(a["transaction_ids"]) for a in detect_duplicates(txs)] == _reference_duplicates(txs)


def test_identical_amounts_are_not_outliers():
    txs = [{"id": str(i), "type": "expense", "category": "rent", "amount_cents": 500_000,
            "transaction_date": "2024-01-01"} for i in range(10)]
    assert detect_unusual_amounts(txs) == []


def test_a_real_sized_statement_is_fast():
    txs = _statement(6000, 1)
    for t in txs:
        t["type"] = "expense"
    started = time.perf_counter()
    detect_unusual_amounts(txs)
    detect_duplicates(txs)
    # Was over a minute. Linear work on 6,000 rows is milliseconds; the bound
    # leaves room for a slow CI machine and none for n².
    assert time.perf_counter() - started < 1.0
