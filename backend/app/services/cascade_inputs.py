"""The measured baseline a cascade simulation may start from: the company's one source of cash and burn.

Cash is the proven balance (`bank_accounts.proven_balances`) and runway/burn are `runway.compute_runway`'s
(both through `company_runway`). Nothing is derived from a net change times a runway, and nothing here is
filled in: what the books cannot prove is absent from the result, and the simulator then names it as
missing instead of running on a constant.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.company_runway import company_runway
from app.services.runway import COMPUTED, NOT_BURNING


async def measured_baseline(db: AsyncSession, org_id: str) -> dict[str, Any]:
    """Keyword arguments (kuruş) for `get_cascade_simulator`: `cash_balance`, `runway_months`, `monthly_burn`.

    Only keys the company's data proves are present.
    """
    block = await company_runway(db, org_id)
    out: dict[str, Any] = {}
    if block.get("opening_cash_cents") is not None:
        out["cash_balance"] = int(block["opening_cash_cents"])
    if block["status"] == COMPUTED and block.get("runway_months") is not None:
        out["runway_months"] = float(block["runway_months"])
    if block["status"] in (COMPUTED, NOT_BURNING) and block.get("avg_monthly_net_cents") is not None:
        out["monthly_burn"] = max(0, -int(block["avg_monthly_net_cents"]))
    return out
