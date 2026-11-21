"""Company size input: read and set the answers, confirm the derived profile.

GET  /api/v1/org/me/size-profile          answers, stored profile, suggestion, options
PUT  /api/v1/org/me/size-profile          store the answers (no profile change)
POST /api/v1/org/me/size-profile/confirm  a person confirms a profile

Owner or admin only (`require_decider`). The system proposes, a human decides: the
answers produce a suggestion, and the profile is stored only by `confirm`. Every
change is a human decision row written in the same transaction. Confirming `micro`
or `small` turns focus mode on unless a person has ever chosen focus mode
themselves (`focus_mode_explicit`); that choice is never overwritten here.
Nothing here changes an authorisation, a threshold or a money rule.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.access import require_decider
from app.api.org import _load_org
from app.database import get_db
from app.models.decision import DecidedVia, DecisionKind
from app.models.organization import Organization
from app.models.user import User
from app.services import decisions
from app.services.size_profile import (
    FOCUS_DEFAULT,
    HEADCOUNT_BAND_LABELS,
    OUTFLOW_BAND_LABELS,
    HeadcountBand,
    OutflowBand,
    SizeProfile,
    SizeProfileSource,
    derive_size_profile,
)

router = APIRouter()


class SizeAnswers(BaseModel):
    """Every field is optional: an unanswered question stays null."""

    monthly_outflow_band: OutflowBand | None = None
    headcount_band: HeadcountBand | None = None
    has_inhouse_finance: bool | None = None


class ConfirmProfile(BaseModel):
    profile: SizeProfile


def _answers(org: Organization) -> dict[str, Any]:
    return {
        "monthly_outflow_band": org.monthly_outflow_band,
        "headcount_band": org.headcount_band,
        "has_inhouse_finance": org.has_inhouse_finance,
    }


def _suggestion(org: Organization) -> dict[str, Any] | None:
    d = derive_size_profile(
        OutflowBand(org.monthly_outflow_band) if org.monthly_outflow_band else None,
        HeadcountBand(org.headcount_band) if org.headcount_band else None,
    )
    if d is None:
        return None
    return {"profile": d.profile.value, "decided_by": d.decided_by, "disagreement": d.disagreement}


def _view(org: Organization, **extra: Any) -> dict[str, Any]:
    return {
        "data": {
            **_answers(org),
            "size_profile": org.size_profile,
            "size_profile_source": org.size_profile_source,
            "size_profile_set_at": org.size_profile_set_at.isoformat() if org.size_profile_set_at else None,
            "size_profile_set_by": org.size_profile_set_by,
            "focus_mode": bool(org.focus_mode),
            "suggestion": _suggestion(org),
            "options": {
                "monthly_outflow_band": [{"value": b.value, "label": s} for b, s in OUTFLOW_BAND_LABELS.items()],
                "headcount_band": [{"value": b.value, "label": s} for b, s in HEADCOUNT_BAND_LABELS.items()],
            },
            **extra,
        },
        "error": None,
    }


@router.get("/org/me/size-profile")
async def get_size_profile(
    user: User = Depends(require_decider), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return _view(await _load_org(user, db))


@router.put("/org/me/size-profile")
async def set_size_answers(
    body: SizeAnswers, user: User = Depends(require_decider), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    org = await _load_org(user, db)
    before = _answers(org)
    after = body.model_dump(mode="json")
    if before != after:
        org.monthly_outflow_band = after["monthly_outflow_band"]
        org.headcount_band = after["headcount_band"]
        org.has_inhouse_finance = after["has_inhouse_finance"]
        await decisions.record_decision(
            db, org_id=str(org.id), kind=DecisionKind.SIZE_PROFILE, target_type="organization",
            target_id=str(org.id), outcome="answers_recorded", decided_via=DecidedVia.HUMAN,
            decided_by=str(user.id), before=before, after=after,
        )
        await db.commit()
        await db.refresh(org)
    return _view(org)


@router.post("/org/me/size-profile/confirm")
async def confirm_size_profile(
    body: ConfirmProfile, user: User = Depends(require_decider), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    org = await _load_org(user, db)
    suggestion = _suggestion(org)
    source = (
        SizeProfileSource.SUGGESTED_ACCEPTED
        if suggestion and suggestion["profile"] == body.profile
        else SizeProfileSource.SELF_REPORTED
    )
    before = {"size_profile": org.size_profile, "focus_mode": bool(org.focus_mode)}
    org.size_profile = body.profile.value
    org.size_profile_source = source.value
    org.size_profile_set_at = datetime.now(UTC)
    org.size_profile_set_by = str(user.id)
    focus_changed = False
    if not org.focus_mode_explicit and org.focus_mode != FOCUS_DEFAULT[body.profile]:
        org.focus_mode = FOCUS_DEFAULT[body.profile]
        focus_changed = True
    await decisions.record_decision(
        db, org_id=str(org.id), kind=DecisionKind.SIZE_PROFILE, target_type="organization",
        target_id=str(org.id), outcome="profile_confirmed", decided_via=DecidedVia.HUMAN,
        decided_by=str(user.id), before=before,
        after={"size_profile": org.size_profile, "focus_mode": bool(org.focus_mode),
               "source": source.value},
    )
    await db.commit()
    await db.refresh(org)
    return _view(org, focus_mode_changed=focus_changed)
