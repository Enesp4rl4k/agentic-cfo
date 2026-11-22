"""The company's materiality threshold: what it is, why, and who confirmed it.

GET  /api/v1/org/me/materiality               what applies now (with its basis), the history of changes, and,
                                              for the owner, the proposal computed from the company's figures
POST /api/v1/org/me/materiality/acknowledge   the OWNER accepts the proposal they were shown
PUT  /api/v1/org/me/materiality               the OWNER sets their own amount, inside the floor and ceiling,
                                              with a reason

The rule and its reasons are in `app/services/materiality.py`. A proposal never applies by itself: until
the owner acknowledges it, the fixed amount that always applied still does. Only the owner may change the
threshold, because an admin who decides under it must not be able to move it (the person a control
constrains does not set the control); an admin may read it and its history. Both writes leave a decision
record (`kind=materiality`) with before, after and the basis, in the same transaction.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.access import require_member
from app.api.auth import get_current_user
from app.api.org import _load_org
from app.database import get_db
from app.models.decision import Decision, DecisionKind
from app.models.user import User
from app.services import materiality
from app.services.acting_role import acting_role

router = APIRouter()


class Acknowledge(BaseModel):
    # The amount the person was shown; refused if the proposal has moved since.
    amount_cents: int = Field(gt=0)


class Override(BaseModel):
    amount_cents: int = Field(gt=0)
    reason: str = Field(min_length=3, max_length=1000)


async def _owner(user: User, db: AsyncSession) -> None:
    """Only the owner changes the threshold (an admin decides under it; see the module docstring)."""
    if await acting_role(db, user) != "owner":
        raise HTTPException(
            status_code=403,
            detail="Onay eşiğini yalnızca şirketin sahibi değiştirebilir; yönetici görüntüleyebilir.",
        )


async def _history(db: AsyncSession, org_id: str) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(Decision)
            .where(Decision.org_id == org_id, Decision.kind == DecisionKind.MATERIALITY.value)
            .order_by(Decision.decided_at.desc())
            .limit(20)
        )
    ).scalars().all()
    names = {
        str(u.id): u.full_name or u.email
        for u in (await db.execute(select(User).where(User.id.in_([r.decided_by for r in rows if r.decided_by] or [""])))).scalars()
    }
    return [
        {
            "outcome": r.outcome, "decided_at": r.decided_at.isoformat(), "reason": r.reason,
            "decided_by": names.get(str(r.decided_by)), "from_cents": (r.before or {}).get("amount_cents"),
            "to_cents": (r.after or {}).get("amount_cents"), "currency": (r.after or {}).get("currency"),
            "basis_text": (r.after or {}).get("basis_text"),
        }
        for r in rows
    ]

async def _view(db: AsyncSession, user: User) -> dict[str, Any]:
    org = await _load_org(user, db)
    data: dict[str, Any] = {
        "current": materiality.current(org),
        "rule": {
            "ratio": materiality.RATIO, "min_months": materiality.MIN_MONTHS, "max_months": materiality.MAX_MONTHS,
            "floor_cents": materiality.FLOOR_CENTS, "ceiling_cents": materiality.CEILING_CENTS,
            "legacy_cents": materiality.LEGACY_CENTS,
        },
        "can_change": False, "proposal": None, "history": await _history(db, str(org.id)),
    }
    if await acting_role(db, user) == "owner":
        data["can_change"] = True
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
    body: Acknowledge, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await _owner(user, db)
    org = await _load_org(user, db)
    try:
        await materiality.acknowledge(db, org, user, body.amount_cents)
    except materiality.MaterialityError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc
    await db.commit()
    return await _view(db, user)


@router.put("/org/me/materiality")
async def set_materiality(
    body: Override, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await _owner(user, db)
    org = await _load_org(user, db)
    try:
        await materiality.override(db, org, user, body.amount_cents, body.reason)
    except materiality.MaterialityError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc
    await db.commit()
    return await _view(db, user)
