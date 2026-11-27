"""The company's runway, read from the database: what the radar and the Monday briefing say.

One formula: `app.services.runway.compute_runway` (the same one the forecast pipeline runs). This module
only supplies its inputs the way the pipeline's company analysis does:

- the balance: the company's proven cash in its base currency (`bank_accounts.proven_balances`: the
  latest proven balance of each account, other currencies left out, unverified statements named);
- the burn: the company ledger's cash rows in that currency (`company_view.ledger_view`, the rows the
  forecast reads), grouped by month and marked complete or not by the statements of those same accounts
  (`coverage.annotate_series`).

Nothing is computed twice: a runway that disagrees with the forecast's is a bug in the inputs, not a
second opinion.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.currency_totals import DEFAULT_BASE, normalise
from app.services.bank_accounts import proven_balances
from app.services.bank_balance import aged_basis, balance_age
from app.services.company_view import ledger_view
from app.services.coverage import annotate_series
from app.services.ledger import BOOK
from app.services.runway import compute_runway


def monthly_series(rows: list[dict[str, Any]], currency: str) -> list[dict[str, Any]]:
    """Cash rows as {month, in, out, net} per month, oldest first (the forecast's own series).

    Only rows in `currency` are added: a row in another currency is never summed into its months.
    """
    months: dict[str, dict[str, int]] = {}
    for row in rows:
        code = normalise(row.get("currency"))
        if code and code != currency:
            continue
        day = str(row.get("transaction_date") or "")
        if len(day) < 7:
            continue
        bucket = months.setdefault(day[:7], {"in": 0, "out": 0})
        bucket["in" if row.get("type") == "income" else "out"] += int(row.get("amount_cents") or 0)
    return [{"month": k, "in": v["in"], "out": v["out"], "net": v["in"] - v["out"]} for k, v in sorted(months.items())]


def mark_missing_statements(series: list[dict[str, Any]], gaps: dict[str, list[str]]) -> list[dict[str, Any]]:
    """A month wholly between two statements of one account is missing, not a quiet month.

    An account's statements are one extent for coverage, so the months between them would read as
    covered; they are marked incomplete and name the account whose statement is missing.
    """
    missing = {m: name for name, months in gaps.items() for m in months}
    out = []
    for m in series:
        if m["month"] in missing:
            m = {**m, "complete": False, "covered": None, "missing_statement": missing[m["month"]]}
            m.pop("assumed", None)
        out.append(m)
    return out


def opening_of(balance: dict[str, Any] | None, anchor: date, excluded: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The proven balance as `compute_runway` takes it, with its age against `anchor`."""
    if balance is None:
        return None
    limit = get_settings().radar_balance_stale_after_days
    age, stale = balance_age(str(balance["date"]), anchor, limit)
    basis, note = aged_basis(balance.get("basis"), None, age, str(balance["date"])[:10])
    return {
        "balance_cents": int(balance["balance_cents"]), "as_of": str(balance["date"])[:10],
        "age_days": age, "stale": stale, "stale_after_days": limit, "filename": balance.get("filename"),
        "basis": basis, "basis_note": note,
        "accounts": list(balance.get("accounts") or []), "excluded": excluded,
        "uncertain": bool(balance.get("uncertain")), "identity_note": balance.get("identity_note"),
    }


async def company_runway(
    db: AsyncSession, org_id: str, anchor: date | None = None, *, balances: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The runway block of this company (`runway.compute_runway`), or why there is none.

    `balances` is `proven_balances` when the caller already loaded it (the radar), so both read one
    account set.
    """
    today = anchor or datetime.now(UTC).date()
    found = balances or await proven_balances(db, org_id)
    currency = found["currency"] or DEFAULT_BASE
    view = await ledger_view(db, org_id)
    rows = list(view.cash) if view is not None else []
    opening = opening_of(found["opening"], today, found["excluded"])
    series = annotate_series(
        monthly_series(rows, currency), rows, list(found["opening"]["extents"]) if found["opening"] else [], today)
    cashflow: dict[str, Any] = {"monthly_series": mark_missing_statements(series, (found["opening"] or {}).get("gaps") or {})}
    if any(r.get("ledger_basis") == BOOK for r in rows):
        cashflow["esas"] = "tahakkuk"
    block = compute_runway(opening, cashflow, currency, unproven=found["excluded"])
    return {**block, "currency": currency, "other_currencies": found["other_currencies"]}
