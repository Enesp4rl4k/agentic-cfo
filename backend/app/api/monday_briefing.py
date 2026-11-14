"""Pazartesi Bülteni (Monday Morning Briefing) API endpoints.

GET  /api/v1/briefing/monday
     Returns the deterministic 3-sentence briefing grounded in the company's radar.
POST /api/v1/briefing/monday/respond
     Records the SME owner's decision ("done" | "deferred" | "dismissed") into DecisionLog.
GET  /api/v1/briefing/monday/deliveries?briefing_id=
     What happened to the briefing's e-mails (sent, held, failed and why).
POST /api/v1/briefing/monday/release
     The company's accountant releases held briefing e-mails.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.models.organization import OrgMembership
from app.models.user import User, UserRole
from app.services import briefing_delivery, outbox
from app.services.monday_briefing import (
    BriefingNeedsAnalysis,
    assemble_monday_briefing,
    record_briefing_response,
)

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
        409: {"description": "Şirketin tamamlanmış bir analizi yok."},
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
    except BriefingNeedsAnalysis as exc:
        raise HTTPException(409, str(exc)) from exc
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


class BriefingReleaseRequest(BaseModel):
    briefing_id: str = Field(..., min_length=1, max_length=100)


@router.get(
    "/briefing/monday/deliveries",
    summary="Pazartesi bülteni e-posta durumu",
    responses={400: {"description": "Kullanıcının organizasyonu yok."}},
)
async def get_briefing_deliveries(
    briefing_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Sent, held or failed, and the reason: nothing about the e-mail is hidden."""
    org_id = _org(user)
    return {"data": await briefing_delivery.deliveries(db, org_id, briefing_id), "error": None}


@router.post(
    "/briefing/monday/release",
    summary="Müşavir bülten e-postasını serbest bırakır",
    responses={
        400: {"description": "Kullanıcının organizasyonu yok."},
        403: {"description": "Bu şirketin mali müşaviri değilsiniz."},
    },
)
async def release_briefing(
    body: BriefingReleaseRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Only the company's accountant releases what was held for them (owner decision K10)."""
    org_id = _org(user)
    membership = (
        await db.execute(
            select(OrgMembership.id).where(
                OrgMembership.user_id == user.id,
                OrgMembership.org_id == org_id,
                OrgMembership.role == UserRole.SMMM.value,
            )
        )
    ).scalar_one_or_none()
    if membership is None:
        raise HTTPException(403, "Bu şirketin mali müşaviri değilsiniz.")
    released = await outbox.release(
        db, org_id=org_id, source=briefing_delivery.SOURCE, source_ref=body.briefing_id
    )
    await db.commit()
    return {"data": {"released": released}, "error": None}
