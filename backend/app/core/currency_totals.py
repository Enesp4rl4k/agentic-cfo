"""Money in different currencies is never added together.

An amount in USD and an amount in TRY are not the same unit, and no exchange rate is
kept here: the repository has no dated, sourced rate (TCMB/EVDS is a macro snapshot, not
a conversion table), and a rate we chose would turn a guess into a figure that reads as a
fact. So every total over money is **per currency**:

- the organisation's base currency gets the headline figure;
- every other currency is reported as its own sub-total ("ayrıca 12.400 USD gider,
  TL'ye çevrilmedi") and is never folded into the base number;
- ratios and month-over-month changes are computed on base-currency amounts only;
- rankings and anomaly detection never compare raw amounts across currencies.

This module is the one place that says which rows belong to which currency. Every
aggregation over ledger or pipeline rows goes through `split_by_currency` (or
`totals_by_currency`), and `tests/test_currency_aggregation_guard.py` fails when a new
money aggregation appears without it.

A row is a mapping (pipeline rows: `currency`, `type`) or an object (ledger rows:
`currency`, `direction`). A row that names no currency is counted as the base currency
only when it is a pipeline mapping, because every producer of those rows writes one
(parsers default to TRY): the ledger column is not nullable.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any, TypeVar

from app.core.tdhp import BILANCO_KATEGORILERI

DEFAULT_BASE = "TRY"

R = TypeVar("R")


def normalise(code: str | None) -> str:
    """ISO 4217 code in capitals; "" when the row names none."""
    return (code or "").strip().upper()


def _get(row: Any, name: str) -> Any:
    return row.get(name) if isinstance(row, dict) else getattr(row, name, None)


def code_of(row: Any, base: str) -> str:
    """The currency a row is in. A mapping with none counts as `base` (see module docstring)."""
    code = normalise(_get(row, "currency"))
    if code:
        return code
    return normalise(base) if isinstance(row, dict) else ""


def direction_of(row: Any) -> str:
    return str(_get(row, "type") or _get(row, "direction") or "")


def amount_of(row: Any) -> int:
    value = _get(row, "amount_cents")
    return int(value or 0)


def split_by_currency(rows: Iterable[R], base: str) -> tuple[list[R], dict[str, list[R]]]:
    """(rows in the base currency, the rest grouped by their own currency)."""
    base = normalise(base) or DEFAULT_BASE
    mine: list[R] = []
    other: dict[str, list[R]] = {}
    for row in rows:
        code = code_of(row, base)
        if code == base:
            mine.append(row)
        else:
            other.setdefault(code, []).append(row)
    return mine, other


def totals_by_currency(rows: Iterable[R], value: Callable[[R], int], base: str = DEFAULT_BASE) -> dict[str, int]:
    """Sum `value(row)` once per currency."""
    totals: dict[str, int] = {}
    for row in rows:
        code = code_of(row, base)
        totals[code] = totals.get(code, 0) + value(row)
    return totals


def _is_income(row: Any) -> bool:
    return direction_of(row) == "income"


def foreign_summaries(
    profit: Iterable[Any], cash: Iterable[Any], base: str
) -> list[dict[str, Any]]:
    """Sub-totals of every non-base currency, for display beside the base figure.

    `profit` rows give revenue and expense (balance-sheet movements are cash, not profit);
    `cash` rows give money in and out. Each currency is summed on its own. Sorted by
    currency code so the output is stable.
    """
    _, profit_other = split_by_currency(profit, base)
    _, cash_other = split_by_currency(cash, base)
    out: list[dict[str, Any]] = []
    for code in sorted(set(profit_other) | set(cash_other)):
        earned = [r for r in profit_other.get(code, []) if _get(r, "category") not in BILANCO_KATEGORILERI]
        moved = cash_other.get(code, [])
        seen = {id(r): r for r in [*profit_other.get(code, []), *moved]}
        out.append({
            "currency": code or "?",
            "revenue_cents": sum(amount_of(r) for r in earned if _is_income(r)),
            "expense_cents": sum(amount_of(r) for r in earned if not _is_income(r)),
            "cash_in_cents": sum(amount_of(r) for r in moved if _is_income(r)),
            "cash_out_cents": sum(amount_of(r) for r in moved if not _is_income(r)),
            "rows": len(seen),
            "assumed_rows": sum(1 for r in seen.values() if _get(r, "currency_assumed")),
        })
    return out


def currency_note(base: str, foreign: list[dict[str, Any]] | None, kind: str = "profit") -> str | None:
    """One sentence saying what was left out of the figures, or None when nothing was.

    `kind` is "profit" (revenue and expense) or "cash" (money in and out).
    """
    if not foreign:
        return None
    base = normalise(base) or DEFAULT_BASE
    keys = (("cash_in_cents", "giriş"), ("cash_out_cents", "çıkış")) if kind == "cash" else (
        ("revenue_cents", "gelir"), ("expense_cents", "gider"))
    parts = []
    for f in foreign:
        bits = [f"{f[k] / 100:,.2f} {f['currency']} {word}" for k, word in keys if f.get(k)]
        parts.append(" ve ".join(bits) if bits else f"{f['currency']} hareketi")
    return (
        f"Toplamlar ve oranlar yalnızca {base} tutarlarıyla hesaplandı; ayrıca "
        + ", ".join(parts) + f" var, {base}'ye çevrilmedi."
    )
