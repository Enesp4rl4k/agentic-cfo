"""How money is written into what the chat model is handed (and into its no-model answers).

A symbol is a claim about the money. The stored dashboard and the CEO summary say which currency their
figures are in (`currency`), how that was decided (`base_state`, `core/currency_totals.effective_base`) and
what was left out (`other_currencies`, never converted). This module turns that into:

- the label an amount carries: the currency the payload states, or none (a bare number) when it states
  none or there is no single currency (several, none confirmed);
- the lines at the top of a context block that tell the model the same thing in words, so it neither
  invents a symbol nor adds a foreign amount to a base-currency figure.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.core.currency_totals import AMBIGUOUS, SINGLE_UNCONFIRMED, fmt_amount, normalise

_PAIRS = (
    ("revenue_cents", "revenue"), ("expense_cents", "expense"),
    ("cash_in_cents", "cash in"), ("cash_out_cents", "cash out"),
)


@dataclass(frozen=True)
class FigureCurrency:
    """The currency a block of figures is in. `code` None means: write bare numbers."""

    code: str | None
    state: str | None = None
    dominant: str | None = None  # ambiguous: the currency the computation ran on (rows in it only)
    others: tuple[Mapping[str, Any], ...] = ()


def figure_currency(*sources: Mapping[str, Any] | None) -> FigureCurrency:
    """Read the currency of figures from the first payload section that states one.

    Each source is a mapping with `currency`, `base_state` and `other_currencies` (a P&L or cash-flow
    section, a CEO financial summary) or `by_currency` (the dashboard's `currency_scope`).
    """
    for src in sources:
        if not src:
            continue
        code = normalise(src.get("currency"))
        state = src.get("base_state")
        others = tuple(src.get("other_currencies") or src.get("by_currency") or ())
        if state == AMBIGUOUS:
            # No single currency: the run used the dominant one for its arithmetic, but nothing is labelled.
            return FigureCurrency(None, AMBIGUOUS, code or None, others)
        if code:
            return FigureCurrency(code, state, None, others)
    return FigureCurrency(None)


def amount(value: float, cur: FigureCurrency, decimals: int = 0) -> str:
    """`value` in major units, labelled with the figures' currency (or bare)."""
    return fmt_amount(value, cur.code, decimals)


def amount_tr(value: float, cur: FigureCurrency) -> str:
    """The same for Turkish text: `₺9.799.500`, `9.799.500 USD`, or `9.799.500`."""
    return fmt_amount(value, cur.code).replace(",", ".")


def _other_line(item: Mapping[str, Any]) -> str:
    code = normalise(item.get("currency")) or "?"
    parts = [f"{fmt_amount(item[key] / 100, code, 2)} {word}" for key, word in _PAIRS if item.get(key)]
    return f"  {code}: " + (", ".join(parts) if parts else "movement only")


def currency_lines(cur: FigureCurrency) -> list[str]:
    """What the model is told about the unit of the figures that follow."""
    if cur.state == AMBIGUOUS:
        ran = f" The figures cover only the rows in {cur.dominant}." if cur.dominant else ""
        lines = [
            "Currency: NOT SINGLE. The data holds several currencies and the company has not confirmed one."
            + ran + " The figures carry no currency label: do not attach a currency symbol to them."
        ]
    elif cur.code is None:
        lines = ["Currency: UNKNOWN. The data does not state one: write the numbers without a currency symbol."]
    elif cur.state == SINGLE_UNCONFIRMED:
        lines = [f"Currency: {cur.code} (the only currency in the data; the company has not confirmed it yet)."]
    else:
        lines = [f"Currency: {cur.code}."]
    if cur.others:
        lines.append(
            "Other currencies are NOT included in the figures and were NOT converted (no exchange rate is "
            "kept); never add them to the figures or convert them:"
        )
        lines += [_other_line(o) for o in cur.others]
    return lines


CURRENCY_RULE = (
    "Write each amount with the currency label exactly as it appears in the data, or with none when the "
    "data shows none; never add, change or convert a currency."
)
