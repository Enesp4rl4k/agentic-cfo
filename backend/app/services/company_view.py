"""Which analysis is "the company's picture" (plan v7 §P0 / W2).

Every completed CFO analysis used to become the company's active analysis —
the context the CEO synthesis, the semantic snapshot, the command center and
the triggers read. Live audit 2026-10-24: approving a broken CSV made it the
active analysis and the company snapshot lost revenue, runway and margin; a
twelve-month view was replaced by one file.

Until the company ledger (plan v5 §F1) builds one view from every source, a new
analysis replaces the current one only when it adds a period: it covers at
least as many months, or it reaches a later month. One with fewer months and
nothing newer (inside the view, or an older single invoice) leaves the view as
it is; one whose period cannot be read never replaces a view that has one. The
person can still apply it explicitly (POST /analysis/{id}/company-view).
"""
from __future__ import annotations

import re
from typing import Any

_MONTH = re.compile(r"^\d{4}-\d{2}$")


def months_of(dashboard: dict[str, Any] | None) -> list[str]:
    """Sorted distinct "YYYY-MM" months the dashboard's cash-flow series covers."""
    series = ((dashboard or {}).get("cashflow") or {}).get("monthly_series") or []
    months = {
        str(m.get("month"))
        for m in series
        if isinstance(m, dict) and _MONTH.match(str(m.get("month") or ""))
    }
    return sorted(months)


def should_replace(
    current: dict[str, Any] | None, new: dict[str, Any] | None
) -> tuple[bool, str]:
    """(replace?, reason) for making `new` the company's active analysis."""
    if not new:
        return False, "no_dashboard"
    current_months = months_of(current)
    if not current_months:
        return True, "no_current_view"
    new_months = months_of(new)
    if not new_months:
        return False, "period_unreadable"
    if set(new_months) <= set(current_months) and len(new_months) < len(current_months):
        return False, "narrower_period_within_current_view"
    # Fewer months and nothing newer: a single invoice from an older month must
    # not replace a twelve-month view (seen live with a UBL-TR sample invoice).
    if len(new_months) < len(current_months) and new_months[-1] <= current_months[-1]:
        return False, "narrower_and_not_newer"
    return True, "adds_a_period"
