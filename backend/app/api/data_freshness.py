"""Org-level data freshness — the "as of" behind every number.

One endpoint for the whole org: which sources feed the system, how old
each one is, the worst state, and the measured age the OKR confidence
uses. Values come straight from `services.freshness` — the same columns
the decision packet strip reads, so the two can never disagree.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.services.freshness import age_from_items, org_overview_freshness

router = APIRouter()

# Worst-first headline order: a source that never synced or stopped syncing
# outranks a merely aging one.
_WORST_ORDER = ("stale", "never", "aging", "unknown", "fresh")


@router.get("/data/freshness")
async def get_data_freshness(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if not current_user.org_id:
        raise HTTPException(status_code=400, detail="Hesap kuruluşa bağlı değil")

    items = await org_overview_freshness(db, current_user.org_id)
    counts = dict.fromkeys(_WORST_ORDER, 0)
    present: set[str] = set()
    for item in items:
        state = item.get("state")
        if state in counts:
            counts[state] += 1
            present.add(state)
    worst = next((s for s in _WORST_ORDER if s in present), "unknown")

    return {
        "data": {
            "items": items,
            "summary": {
                "counts": counts,
                "worst": worst if items else "unknown",
                "as_of": datetime.now(UTC).isoformat(),
            },
            "age": age_from_items(items),
        }
    }
