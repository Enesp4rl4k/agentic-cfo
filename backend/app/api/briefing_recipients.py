"""Whether the Monday briefing also goes to the company's accountant.

GET /api/v1/org/me/briefing-recipients    the standing choice, whether the company has an accountant, and
                                          the profile's suggestion (a suggestion, never a setting)
PUT /api/v1/org/me/briefing-recipients    owner or admin: send_to_smmm true or false (a decision record)

This only names a recipient. Nothing is sent from here: the briefing's e-mails are written to the outbox
per recipient and, when the company has an accountant, held until the accountant releases them
(`services/briefing_delivery`, ADR 0003 and 0008). Choosing the accountant adds their address to that
existing flow; it adds no way to send.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.access import require_decider, require_member
from app.api.org import _load_org
from app.database import get_db
from app.models.decision import DecidedVia, DecisionKind
from app.models.user import User
from app.services import accountant, decisions
from app.services.size_profile import profile_defaults

router = APIRouter()


class Recipients(BaseModel):
    send_to_smmm: bool


async def _view(db: AsyncSession, user: User) -> dict[str, Any]:
    org = await _load_org(user, db)
    defaults = profile_defaults(org.size_profile)
    return {
        "data": {
            "send_to_smmm": bool(org.briefing_to_smmm),
            "has_smmm": await accountant.has_active_smmm(db, str(org.id)),
            "suggested": bool(defaults and defaults["briefing_to_smmm_suggested"]),
        },
        "error": None,
    }


@router.get("/org/me/briefing-recipients")
async def get_recipients(
    user: User = Depends(require_member), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return await _view(db, user)


@router.put("/org/me/briefing-recipients")
async def set_recipients(
    body: Recipients, user: User = Depends(require_decider), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    org = await _load_org(user, db)
    if body.send_to_smmm and not await accountant.has_active_smmm(db, str(org.id)):
        raise HTTPException(
            status_code=422,
            detail="Şirketin mali müşaviri yok: bülteni ona göndermek için önce mali müşavir davet edin.",
        )
    if bool(org.briefing_to_smmm) != body.send_to_smmm:
        before = {"send_to_smmm": bool(org.briefing_to_smmm)}
        org.briefing_to_smmm = body.send_to_smmm
        await decisions.record_decision(
            db, org_id=str(org.id), kind=DecisionKind.BRIEFING_RECIPIENTS, target_type="organization",
            target_id=str(org.id), outcome="smmm_added" if body.send_to_smmm else "smmm_removed",
            decided_via=DecidedVia.HUMAN, decided_by=str(user.id), before=before,
            after={"send_to_smmm": body.send_to_smmm},
        )
        await db.commit()
    return await _view(db, user)
