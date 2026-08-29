"""
Financial Calculation Primitives — DRY & KISS Principles.

Centralises currency conversion, safe division, profit margin,
and variance formulas to prevent duplicated and brittle math across skills.
Amounts are consistently represented as INTEGER cents/kuruş.
"""
from __future__ import annotations

import math


def safe_div(
    numerator: float,
    denominator: float,
    default: float = 0.0,
) -> float:
    """Safe division preventing ZeroDivisionError and NaN."""
    if not denominator:
        return default
    try:
        res = float(numerator) / float(denominator)
        return default if math.isnan(res) else res
    except (ZeroDivisionError, ValueError, OverflowError):
        return default


def cents_to_amount(cents: float | None) -> float:
    """Convert integer cents/kuruş to floating major currency units (e.g. 10000 -> 100.0)."""
    if cents is None:
        return 0.0
    return round(float(cents) / 100.0, 2)


def amount_to_cents(amount: float | str | None) -> int:
    """Convert major currency amount to integer cents/kuruş (e.g. 100.50 -> 10050)."""
    if amount is None:
        return 0
    try:
        return round(float(amount) * 100)
    except (ValueError, TypeError):
        return 0


def calc_margin(part_cents: int, total_cents: int) -> float:
    """Calculate percentage margin (0.0% to 100.0%)."""
    if not total_cents:
        return 0.0
    return round(safe_div(part_cents, total_cents) * 100.0, 2)


def calc_variance_pct(actual: float, budgeted: float) -> float:
    """Calculate percentage variance between actual and budgeted."""
    if not budgeted:
        return 0.0 if not actual else 100.0
    return round(safe_div(actual - budgeted, budgeted) * 100.0, 2)


def calc_growth_pct(current: float, previous: float) -> float:
    """Calculate period-over-period percentage growth."""
    if not previous:
        return 0.0 if not current else 100.0
    return round(safe_div(current - previous, previous) * 100.0, 2)


def format_currency_try(cents: float, symbol: str = "₺") -> str:
    """Format cents into readable Turkish Lira string."""
    amt = cents_to_amount(cents)
    return f"{symbol}{amt:,.2f}"


def format_currency_usd(cents: float, symbol: str = "$") -> str:
    """Format cents into readable USD string."""
    amt = cents_to_amount(cents)
    return f"{symbol}{amt:,.2f}"
