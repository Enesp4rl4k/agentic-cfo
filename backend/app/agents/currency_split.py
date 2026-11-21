"""The currency step of the CFO pipeline, kept out of `orchestrator.py` (600-line ceiling)."""
from __future__ import annotations

import logging
from typing import Any

from app.agents.state import CFOState
from app.core.currency_totals import (
    AMBIGUOUS,
    DEFAULT_BASE,
    count_currencies,
    effective_base,
    foreign_summaries,
    split_by_currency,
)

logger = logging.getLogger(__name__)


def keep_base_currency(state: CFOState, patch: dict[str, Any]) -> None:
    """Every step after ingestion reads rows of ONE currency, and says which and why.

    Amounts in different currencies are not the same unit and no exchange rate is kept
    (`core/currency_totals`), so the rows in any other currency leave `transactions` here:
    no total, ratio, ranking or anomaly check downstream can mix them. What was left out
    travels as `foreign_totals`, one sub-total per currency, for the report to show beside
    the figures, and `base_state` says how the currency was decided (`effective_base`):

    - confirmed: the confirmed currency;
    - single_unconfirmed: the only currency in the data (nothing is dropped, outputs say it is unconfirmed);
    - ambiguous: no confirmed currency and several in the data. The run goes on the dominant currency by
      row count, every output is labelled with it, and the run is held for a person (`awaiting_review`);
    - no_data: nothing to split.

    A ledger-fed run arrives already split (`company_view`). `state["base_currency"]` is the CONFIRMED
    currency or None, never the column default.
    """
    txs = patch.get("transactions")
    if txs is None:
        return
    ledger = state.get("ledger_view")
    if ledger is not None:
        base = ledger.get("base_currency") or DEFAULT_BASE
        base_state = ledger.get("base_state") or "confirmed"
        kept, foreign = txs, list(ledger.get("foreign") or [])
    else:
        eb = effective_base(state.get("base_currency"), count_currencies(txs))
        base, base_state = eb.run_currency or DEFAULT_BASE, eb.state
        kept, other = split_by_currency(txs, base)
        foreign = foreign_summaries(txs, txs, base)
        patch["foreign_transactions"] = [row for rows in other.values() for row in rows]
    patch["base_currency"] = base
    patch["base_state"] = base_state
    patch["transactions"] = kept
    patch["foreign_totals"] = foreign
    if base_state == AMBIGUOUS:
        patch["awaiting_review"] = True


async def stored_base_currency(org_id: str | None) -> str | None:
    """The organisation's CONFIRMED base currency (None when unconfirmed), for a run not handed one."""
    from app.services.org_identity import own_base_currency

    return await own_base_currency(org_id)
