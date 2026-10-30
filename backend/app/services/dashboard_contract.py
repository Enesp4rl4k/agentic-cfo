"""One reader for the persisted CFO dashboard (plan v6 §S4, started in §S0).

`Report.data` / `CompanyContext.last_cfo_result` carry the dashboard that
`report_agent` writes: **lira** scalars (not kuruş), period totals (not
monthly), and opex **by category** — there is no `total_opex` key. Every module
that read it guessed: the risk KRI asked for `total_opex` and was never
computed; the stress test read lira as kuruş; a report divided lira by 100.

Readers go through these accessors instead of `pnl.get(...)`, so the shape is
answered once.
"""
from __future__ import annotations

from typing import Any


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def period_opex(pnl: dict[str, Any] | None) -> float | None:
    """Period opex in lira: the per-category `opex` the dashboard carries, or
    `total_opex` (the raw pnl_agent shape). None if neither is readable."""
    pnl = pnl or {}
    total = _num(pnl.get("total_opex"))
    if total is not None:
        return total
    by_category = pnl.get("opex")
    if not isinstance(by_category, dict) or not by_category:
        return None
    parts = [_num(v) for v in by_category.values()]
    if any(p is None for p in parts):
        return None
    return sum(p for p in parts if p is not None)


def revenue(pnl: dict[str, Any] | None) -> float | None:
    """Period revenue in lira."""
    return _num((pnl or {}).get("revenue"))
