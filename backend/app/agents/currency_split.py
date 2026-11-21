"""The currency step of the CFO pipeline, kept out of `orchestrator.py` (600-line ceiling)."""
from __future__ import annotations

import logging
from typing import Any

from app.agents.state import CFOState
from app.core.currency_totals import DEFAULT_BASE, foreign_summaries, normalise, split_by_currency

logger = logging.getLogger(__name__)


def keep_base_currency(state: CFOState, patch: dict[str, Any]) -> None:
    """Every step after ingestion reads base-currency rows only.

    Amounts in different currencies are not the same unit and no exchange rate is kept
    (`core/currency_totals`), so the rows in any other currency leave `transactions` here:
    no total, ratio, ranking or anomaly check downstream can mix them. What was left out
    travels as `foreign_totals`, one sub-total per currency, for the report to show beside
    the base figures. A ledger-fed run arrives already split (`company_view`).
    """
    txs = patch.get("transactions")
    if txs is None:
        return
    ledger = state.get("ledger_view")
    base = normalise((ledger or {}).get("base_currency") or state.get("base_currency")) or DEFAULT_BASE
    kept, _ = split_by_currency(txs, base)
    patch["base_currency"] = base
    patch["transactions"] = kept
    patch["foreign_totals"] = (
        list(ledger.get("foreign") or []) if ledger is not None else foreign_summaries(txs, txs, base)
    )


async def stored_base_currency(org_id: str | None) -> str | None:
    """The organisation's stored base currency, for a run that was not handed one."""
    if not org_id:
        return None
    try:
        from sqlalchemy import select

        from app.database import session_factory
        from app.models.organization import Organization

        async with session_factory()() as db:
            return (await db.execute(
                select(Organization.base_currency).where(Organization.id == org_id)
            )).scalar_one_or_none()
    except Exception as exc:  # a run is not blocked on this: the default base is TRY
        logger.warning("base currency lookup failed for org %s: %s", org_id, exc)
        return None
