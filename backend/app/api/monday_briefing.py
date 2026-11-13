"""Pazartesi Bülteni (Monday Morning Briefing) API endpoints.

GET  /api/v1/briefing/monday
     Returns the deterministic 3-sentence briefing grounded in the company's radar.
POST /api/v1/briefing/monday/respond
     Records the SME owner's decision ("done" | "deferred" | "dismissed") into DecisionLog.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.services.monday_briefing import assemble_monday_briefing, record_briefing_response

router = APIRouter()


def _org(user: User) -> str:
    if not user.org_id:
        raise HTTPException(400, "Kullanıcının organizasyonu yok.")
    return str(user.org_id)


class BriefingRespondRequest(BaseModel):
    response: str = Field(..., description="Patron yanıtı: 'done' | 'deferred' | 'dismissed'")
    note: str | None = Field(default=None, description="Ek açıklama veya gerekçe")
    anchor_date: str | None = Field(
        default=None, description="Opsiyonel referans tarihi (YYYY-AA-GG)"
    )


@router.get(
    "/briefing/monday",
    summary="Pazartesi sabah bülteni",
    responses={400: {"description": "Kullanıcının organizasyonu yok veya geçersiz tarih."}},
)
async def get_monday_briefing(
    anchor_date: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Return the deterministic 3-sentence Monday morning briefing from the cash radar."""
    org_id = _org(user)
    parsed_anchor: date | None = None
    if anchor_date:
        try:
            parsed_anchor = date.fromisoformat(anchor_date)
        except ValueError:
            raise HTTPException(400, "Geçersiz tarih biçimi (YYYY-AA-GG bekleniyor).") from None

    briefing = await assemble_monday_briefing(db, org_id, anchor_date=parsed_anchor)
    return {"data": briefing.to_dict(), "error": None}


@router.post(
    "/briefing/monday/respond",
    summary="Pazartesi bülteni aksiyon yanıtı",
    responses={
        400: {"description": "Kullanıcının organizasyonu yok veya geçersiz tarih."},
        422: {"description": "Geçersiz yanıt değeri."},
    },
)
async def respond_to_monday_briefing(
    body: BriefingRespondRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Record the owner's response to the Monday briefing in the DecisionLog."""
    org_id = _org(user)
    parsed_anchor: date | None = None
    if body.anchor_date:
        try:
            parsed_anchor = date.fromisoformat(body.anchor_date)
        except ValueError:
            raise HTTPException(400, "Geçersiz tarih biçimi (YYYY-AA-GG bekleniyor).") from None

    briefing = await assemble_monday_briefing(db, org_id, anchor_date=parsed_anchor)
    try:
        decision = await record_briefing_response(
            db,
            org_id=org_id,
            user_id=str(user.id),
            briefing=briefing,
            response=body.response,
            note=body.note,
        )
        await db.commit()
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    return {
        "data": {
            "decision_id": decision.id,
            "status": decision.status,
            "chosen_option_label": decision.chosen_option_label,
            "briefing_id": briefing.briefing_id,
        },
        "error": None,
    }
