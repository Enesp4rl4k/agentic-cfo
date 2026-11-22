"""The company's materiality threshold: what it is, why, and who confirmed it.

GET  /api/v1/org/me/materiality               what applies now (with its basis) and, for an owner or admin,
                                              the proposal computed from the company's own figures
POST /api/v1/org/me/materiality/acknowledge   an owner or admin accepts the proposal they were shown
PUT  /api/v1/org/me/materiality               an owner or admin sets their own amount (recorded with a reason)

The rule and its reasons are in `app/services/materiality.py`. A proposal never applies by itself: until
an owner or admin acknowledges it, the fixed amount that always applied still does. Both writes leave a
decision record (`kind=materiality`) with before, after and the basis, in the same transaction.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.access import require_decider, require_member
from app.api.org import _load_org
from app.database import get_db
from app.models.user import User
from app.services import materiality
from app.services.acting_role import acting_role

router = APIRouter()


class Acknowledge(BaseModel):
    # The amount the person was shown; refused if the proposal has moved since.
    amount_cents: int = Field(gt=0)


class Override(BaseModel):
    amount_cents: int = Field(gt=0)
    reason: str | None = Field(default=None, max_length=1000)


async def _view(db: AsyncSession, user: User) -> dict[str, Any]:
    org = await _load_org(user, db)
    data: dict[str, Any] = {
        "current": materiality.current(org),
        "rule": {
            "ratio": materiality.RATIO, "min_months": materiality.MIN_MONTHS, "max_months": materiality.MAX_MONTHS,
            "floor_cents": materiality.FLOOR_CENTS, "ceiling_cents": materiality.CEILING_CENTS,
            "legacy_cents": materiality.LEGACY_CENTS,
        },
        "can_decide": False, "proposal": None,
    }
    if await acting_role(db, user) in ("owner", "admin"):
        data["can_decide"] = True
        proposal = await materiality.propose(db, org)
        if proposal is not None:
            applied = org.materiality_applied
            proposal["basis_text"] = materiality.basis_text(proposal)
            # Offered again only when it is not what already applies: nothing nags about a settled value.
            proposal["differs_from_current"] = not applied or int(applied["amount_cents"]) != int(proposal["amount_cents"])
        data["proposal"] = proposal
    return {"data": data, "error": None}


@router.get("/org/me/materiality")
async def get_materiality(
    user: User = Depends(require_member), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return await _view(db, user)


@router.post("/org/me/materiality/acknowledge")
async def acknowledge_materiality(
    body: Acknowledge, user: User = Depends(require_decider), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    org = await _load_org(user, db)
    try:
        await materiality.acknowledge(db, org, user, body.amount_cents)
    except materiality.MaterialityError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc
    await db.commit()
    return await _view(db, user)


@router.put("/org/me/materiality")
async def set_materiality(
    body: Override, user: User = Depends(require_decider), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    org = await _load_org(user, db)
    try:
        await materiality.override(db, org, user, body.amount_cents, body.reason)
    except materiality.MaterialityError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc
    await db.commit()
    return await _view(db, user)
