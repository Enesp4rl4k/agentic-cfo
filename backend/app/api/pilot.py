"""
Pilot Program API

POST /api/v1/pilot/invite/generate   — platform operator invites an e-mail address to open a NEW company
POST /api/v1/pilot/invite/preview    — what the invitation page needs before sign-up (by secret token)
GET  /api/v1/pilot/invites           — operator: list invites + state
DELETE /api/v1/pilot/invite/{id}     — operator: revoke an unused invite

POST /api/v1/pilot/feedback          — submit feedback (auth required)
GET  /api/v1/pilot/feedback          — operator: list all feedback
GET  /api/v1/pilot/feedback/summary  — operator: NPS + rating aggregates
GET  /api/v1/pilot/status            — operator view: registration mode, users, invites

The invite is redeemed by `POST /auth/register` with its token (services/pilot_invites.py describes the
whole flow). There is no way to read a token back: it is e-mailed once and stored only as a digest.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.access import require_platform_operator
from app.api.auth import get_current_user
from app.database import get_db
from app.models.pilot import PilotInvite, UserFeedback
from app.models.user import User
from app.services import mail_capability, outbox, pilot_invites, registration

router = APIRouter()
logger = logging.getLogger(__name__)



# ── Pydantic schemas ──────────────────────────────────────────────────────────

class GenerateInviteRequest(BaseModel):
    email: EmailStr
    company_name: str = Field(min_length=2, max_length=200)
    note: str | None = Field(default=None, max_length=500)
    expire_days: int | None = Field(default=None, ge=1, le=365)


class PreviewRequest(BaseModel):
    token: str = Field(min_length=8, max_length=128)


class FeedbackRequest(BaseModel):
    job_id: str | None = None
    nps_score: int | None = Field(default=None, ge=0, le=10)
    analysis_rating: int | None = Field(default=None, ge=1, le=5)
    accuracy_rating: int | None = Field(default=None, ge=1, le=5)
    usefulness_rating: int | None = Field(default=None, ge=1, le=5)
    speed_rating: int | None = Field(default=None, ge=1, le=5)
    comment: str | None = Field(default=None, max_length=2000)
    biggest_benefit: str | None = Field(default=None, max_length=1000)
    biggest_gap: str | None = Field(default=None, max_length=1000)
    page_context: str | None = Field(default=None, max_length=100)


# ── Pilot status (operators) ─────────────────────────────────────────────────

@router.get("/pilot/status", dependencies=[Depends(require_platform_operator)])
async def pilot_status(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Operator view: the registration mode and how many accounts and open invites there are.

    There is no user cap: in `invite_only` the number of companies is the number of invites an operator
    issued, and that is the cap."""
    users = (await db.execute(select(func.count()).select_from(User).where(User.is_active))).scalar() or 0
    open_invites = (
        await db.execute(
            select(func.count()).select_from(PilotInvite).where(
                PilotInvite.used.is_(False), PilotInvite.token_hash.is_not(None),
                or_(PilotInvite.expires_at.is_(None), PilotInvite.expires_at > datetime.now(UTC)),
            )
        )
    ).scalar() or 0
    return {
        "data": {
            "registration_mode": registration.mode(),
            "current_users": users,
            "available_invites": open_invites,
            "mail_delivery": mail_capability.delivery(),
        },
        "error": None,
    }


# ── Invite management (operators) ────────────────────────────────────────────

@router.post("/pilot/invite/generate", status_code=201, dependencies=[Depends(require_platform_operator)])
async def generate_invite(
    body: GenerateInviteRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Operator: invite one address to create a new company. The link goes out by e-mail; it is not returned.

    With no mail sender configured nothing is created and the answer says so (503): an invite nobody can
    receive would only look like a success."""
    try:
        invite = await pilot_invites.issue(
            db, operator_id=str(current_user.id), email=str(body.email), company_name=body.company_name,
            note=body.note, expire_days=body.expire_days,
        )
    except pilot_invites.PilotInviteError as err:
        raise HTTPException(err.status_code, detail=err.detail) from None
    await db.commit()
    outbox.kick()
    logger.info("Pilot: invite %s issued by operator %s", invite.id, current_user.id)
    return {
        "data": {
            "invite_id": invite.id,
            "email": invite.email,
            "company_name": invite.company_name,
            "expires_at": invite.expires_at.isoformat() if invite.expires_at else None,
            "email_sent": True,  # handed to the outbox; its delivery is recorded there
            **mail_capability.fields(),
        },
        "error": None,
    }


@router.post("/pilot/invite/preview")
async def preview_invite(body: PreviewRequest, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """The invitation page's first call: whose invitation, for which company, in what state.

    The token is the secret (e-mailed to the invitee); whoever holds it may read this. A POST, so the
    token is in the body and not in a URL that logs and proxies keep."""
    invite = await pilot_invites.find(db, body.token)
    current = pilot_invites.state(invite)
    if invite is None or current == "unknown":
        return {"data": {"state": "unknown"}, "error": None}
    return {
        "data": {
            "state": current,
            "email": invite.email,
            "company_name": invite.company_name,
            "registration_closed": registration.mode() == "closed",
        },
        "error": None,
    }


@router.get("/pilot/invites", dependencies=[Depends(require_platform_operator)])
async def list_invites(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Operator: every invite with its state. No token and no link: those exist only in the e-mail."""
    result = await db.execute(select(PilotInvite).order_by(PilotInvite.created_at.desc()))
    return {
        "data": [
            {
                "id": i.id,
                "code": i.code,
                "email": i.email,
                "company_name": i.company_name,
                "note": i.note,
                "state": pilot_invites.state(i),
                "used": i.used,
                "used_by": i.used_by_user_id,
                "used_at": i.used_at.isoformat() if i.used_at else None,
                "expires_at": i.expires_at.isoformat() if i.expires_at else None,
                "created_at": i.created_at.isoformat(),
            }
            for i in result.scalars().all()
        ],
        "error": None,
    }


@router.delete("/pilot/invite/{invite_id}", dependencies=[Depends(require_platform_operator)])
async def revoke_invite(
    invite_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Operator: revoke an unused invite (its link stops working)."""
    invite = await db.get(PilotInvite, invite_id)
    if not invite:
        raise HTTPException(404, detail="Davet bulunamadı.")
    if invite.used:
        raise HTTPException(400, detail="Kullanılmış davet iptal edilemez.")
    await db.delete(invite)
    await db.commit()
    return {"data": {"revoked": True}, "error": None}


# ── Feedback ──────────────────────────────────────────────────────────────────

@router.post("/pilot/feedback", status_code=201)
async def submit_feedback(
    body: FeedbackRequest,
    db: AsyncSession = Depends(get_db),
    # Was `Depends(lambda: None)`: "auth optional" that could never see a
    # user, so every piece of feedback was anonymous and anyone could post it.
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Submit post-analysis feedback. Auth optional — anonymous feedback allowed."""
    fb = UserFeedback(
        user_id=current_user.id if current_user else None,
        job_id=body.job_id,
        org_id=current_user.org_id if current_user else None,
        nps_score=body.nps_score,
        analysis_rating=body.analysis_rating,
        accuracy_rating=body.accuracy_rating,
        usefulness_rating=body.usefulness_rating,
        speed_rating=body.speed_rating,
        comment=body.comment,
        biggest_benefit=body.biggest_benefit,
        biggest_gap=body.biggest_gap,
        page_context=body.page_context,
    )
    db.add(fb)
    await db.commit()
    await db.refresh(fb)

    logger.info(
        "Feedback submitted: id=%s nps=%s rating=%s",
        fb.id, body.nps_score, body.analysis_rating,
    )

    return {"data": {"feedback_id": fb.id}, "error": None}


@router.get("/pilot/feedback", dependencies=[Depends(require_platform_operator)])
async def list_feedback(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Admin: list all feedback entries."""
    result = await db.execute(
        select(UserFeedback)
        .order_by(UserFeedback.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    entries = result.scalars().all()

    count_result = await db.execute(select(func.count()).select_from(UserFeedback))
    total = count_result.scalar() or 0

    return {
        "data": {
            "total": total,
            "entries": [
                {
                    "id": f.id,
                    "user_id": f.user_id,
                    "job_id": f.job_id,
                    "nps_score": f.nps_score,
                    "analysis_rating": f.analysis_rating,
                    "accuracy_rating": f.accuracy_rating,
                    "usefulness_rating": f.usefulness_rating,
                    "speed_rating": f.speed_rating,
                    "comment": f.comment,
                    "biggest_benefit": f.biggest_benefit,
                    "biggest_gap": f.biggest_gap,
                    "page_context": f.page_context,
                    "created_at": f.created_at.isoformat(),
                }
                for f in entries
            ],
        },
        "error": None,
    }


@router.get("/pilot/feedback/summary", dependencies=[Depends(require_platform_operator)])
async def feedback_summary(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Admin: aggregate NPS + ratings summary."""
    result = await db.execute(select(UserFeedback))
    all_fb = result.scalars().all()

    if not all_fb:
        return {
            "data": {
                "total_responses": 0,
                "nps_score": None,
                "avg_analysis_rating": None,
                "avg_accuracy_rating": None,
                "avg_usefulness_rating": None,
                "avg_speed_rating": None,
                "promoters": 0,
                "passives": 0,
                "detractors": 0,
                "top_benefits": [],
                "top_gaps": [],
            },
            "error": None,
        }

    # NPS calculation
    nps_scores = [f.nps_score for f in all_fb if f.nps_score is not None]
    promoters  = sum(1 for s in nps_scores if s >= 9)
    passives   = sum(1 for s in nps_scores if 7 <= s <= 8)
    detractors = sum(1 for s in nps_scores if s <= 6)
    nps = round(((promoters - detractors) / len(nps_scores)) * 100) if nps_scores else None

    def _avg(values: list[int | None]) -> float | None:
        filtered = [v for v in values if v is not None]
        return round(sum(filtered) / len(filtered), 2) if filtered else None

    return {
        "data": {
            "total_responses": len(all_fb),
            "nps_score": nps,
            "avg_analysis_rating": _avg([f.analysis_rating for f in all_fb]),
            "avg_accuracy_rating": _avg([f.accuracy_rating for f in all_fb]),
            "avg_usefulness_rating": _avg([f.usefulness_rating for f in all_fb]),
            "avg_speed_rating": _avg([f.speed_rating for f in all_fb]),
            "promoters": promoters,
            "passives": passives,
            "detractors": detractors,
            "top_benefits": [
                f.biggest_benefit for f in all_fb
                if f.biggest_benefit
            ][:10],
            "top_gaps": [
                f.biggest_gap for f in all_fb
                if f.biggest_gap
            ][:10],
        },
        "error": None,
    }
