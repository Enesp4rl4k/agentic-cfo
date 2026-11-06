"""Plan v9 §K1 — a statement's closing balance is believed only when its running balances chain.

Figures written by hand: 50,000.00 opening, +10,000.00, -4,000.00, +1,500.50.
"""
from __future__ import annotations

from typing import Any

from app.services.bank_balance import closing_balance


def _row(day: str, amount: int, kind: str, balance: int | None) -> dict[str, Any]:
    return {"transaction_date": day, "amount_cents": amount, "type": kind, "balance_cents": balance}


OLDEST_FIRST = [
    _row("2025-04-02", 10_000_00, "income", 60_000_00),
    _row("2025-04-05", 4_000_00, "expense", 56_000_00),
    _row("2025-04-09", 1_500_50, "income", 57_500_50),
]


def test_an_oldest_first_statement_closes_on_its_last_row():
    assert closing_balance(OLDEST_FIRST) == {"date": "2025-04-09", "balance_cents": 57_500_50}


def test_a_newest_first_statement_closes_on_its_first_row():
    assert closing_balance(OLDEST_FIRST[::-1]) == {"date": "2025-04-09", "balance_cents": 57_500_50}


def test_balances_that_do_not_chain_prove_nothing():
    broken = [*OLDEST_FIRST[:2], _row("2025-04-09", 1_500_50, "income", 57_000_00)]
    assert closing_balance(broken) is None


def test_a_row_without_a_balance_proves_nothing():
    missing = [*OLDEST_FIRST[:2], _row("2025-04-09", 1_500_50, "income", None)]
    assert closing_balance(missing) is None


def test_a_single_row_has_nothing_to_chain_to():
    assert closing_balance(OLDEST_FIRST[:1]) is None
    assert closing_balance([]) is None
