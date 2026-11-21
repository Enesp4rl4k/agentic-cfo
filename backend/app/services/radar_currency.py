"""What the cash radar leaves out because it is in another currency, said per currency.

The radar's weeks are in one currency. Rent and tax payments seen in another currency, and a bank
balance in another (or unknown) currency, are never added to those weeks and never converted: each is
reported on its own line, the way other-currency open items are.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.currency_totals import fmt_money, normalise
from app.models.canonical_transaction import CanonicalTransaction, money_rows


def usable_balance(balance: dict[str, Any] | None, cur: str) -> tuple[dict[str, Any] | None, str | None]:
    """(the balance if it is in `cur`, else None; a not-included line saying why a balance was not used)."""
    if balance is None:
        return None, None
    code = normalise(balance.get("currency"))
    if code == cur:
        return balance, None
    what = fmt_money(balance["balance_cents"], code)  # an unknown currency reads "(para birimi bilinmiyor)"
    return None, (
        f"{what} tutarındaki banka bakiyesi ({balance['date']}) {cur} radarına eklenmedi: "
        f"{cur} cinsinden kanıtlanmış başlangıç nakdi yok"
    )


async def other_currency_projections(
    db: AsyncSession, org_id: str, cur: str, anchor: date, weeks: int
) -> dict[str, dict[str, int]]:
    """{currency: recurring and tax projections} for every currency but `cur`, inside the horizon."""
    from app.services.recurring_obligations import detect_recurring_obligations, project_recurring_obligations
    from app.services.tax_calendar import project_tax_obligations

    codes = (
        await db.execute(
            select(CanonicalTransaction.currency)
            .where(
                CanonicalTransaction.org_id == org_id,
                CanonicalTransaction.basis == "cash",
                CanonicalTransaction.ledger_status == "active",
                CanonicalTransaction.direction == "expense",
                CanonicalTransaction.amount_cents > 0,
                money_rows(),
            )
            .distinct()
        )
    ).scalars().all()
    out: dict[str, dict[str, int]] = {}
    for code in sorted({normalise(c) for c in codes} - {cur, ""}):
        recurring = project_recurring_obligations(await detect_recurring_obligations(db, org_id, code), anchor, weeks)
        taxes = await project_tax_obligations(db, org_id, anchor, weeks, code)
        rec, tax = sum(p.amount_cents for p in recurring), sum(p.amount_cents for p in taxes)
        if rec or tax:
            out[code] = {"recurring_payable_cents": rec, "tax_payable_cents": tax}
    return out
