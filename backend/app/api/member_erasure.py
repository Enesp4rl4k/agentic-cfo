"""KVKK Md. 7 / 11 — erase one person while the company stays (pseudonymous retention).

  POST /privacy/member-erasure                         a member, for their own account
  POST /privacy/org/members/{user_id}/erasure          owner | admin, for a member who has left (see below)
  POST /privacy/member-erasure/{request_id}/cancel     the person, the one who asked, or a platform operator
  GET  /privacy/erasure-requests                       the caller's own request; owner/admin also the company's

One call with the person's e-mail address typed back as confirmation: the account stays usable and the
destructive step is SCHEDULED after the cooling-off window (ERASURE_COOLING_OFF_DAYS), cancellable until then.
What the step does and keeps: `app.services.privacy.member_erasure`. A sole owner is refused (409
`sole_owner`): they transfer ownership or erase the company.

An owner may erase another member only if that member belongs to no other company, and an admin only a member below
admin (the same rule as removing a member, `app.api.org`).
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.access import ensure_tenant, is_platform_operator
from app.api.auth import get_current_user
from app.config import get_settings
from app.core.email_address import normalize_email
from app.database import get_db
from app.models.erasure_record import OrgErasureRequest
from app.models.organization import OrgMembership
from app.models.user import User
from app.services.acting_role import acting_role
from app.services.org_erasure import hash_id
from app.services.privacy import erasure_flow
from app.services.privacy.member_erasure import blockers, is_tombstone, pseudonym

router = APIRouter()
logger = logging.getLogger(__name__)
NOT_FOUND = "Kayıt bulunamadı."


class MemberErasureBody(BaseModel):
    # The e-mail address of the person to be erased, typed back: a deliberate act, not a stray click.
    confirmation: str = Field(min_length=3, max_length=255)


async def _live_requests(db: AsyncSession, **where: Any) -> list[OrgErasureRequest]:
    stmt = select(OrgErasureRequest).where(
        OrgErasureRequest.scope == "member", OrgErasureRequest.status.in_((erasure_flow.SCHEDULED, erasure_flow.PENDING)))
    for col, value in where.items():
        stmt = stmt.where(getattr(OrgErasureRequest, col) == value)
    return list((await db.execute(stmt)).scalars())


async def _schedule_member(
    db: AsyncSession, target: User, *, initiated_by: str, requester: User, confirmation: str
) -> dict[str, Any]:
    if is_tombstone(target.email):
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    if normalize_email(confirmation) != normalize_email(target.email):
        raise HTTPException(status_code=422, detail="Onay, silinecek kişinin e-posta adresi olmalı.")
    if await blockers(db, str(target.id)):
        raise HTTPException(
            status_code=409,
            detail="sole_owner: bu kişi bir şirketin tek sahibi. Önce sahipliği devredin veya şirket verisinin silinmesini başlatın.",
        )
    if await _live_requests(db, target_user_id=str(target.id)):
        raise HTTPException(status_code=409, detail="Bu kişi için bekleyen bir silme talebi var.")
    now = datetime.now(UTC)
    who = hash_id("user", str(requester.id))
    req = OrgErasureRequest(
        target_org_id=None, target_user_id=str(target.id), org_hash=hash_id("member", str(target.id)), mode="anonymise",
        status=erasure_flow.PENDING, scope="member", initiated_by=initiated_by, requested_by_user_id=str(requester.id),
        requested_by_hash=who, requested_at=now, expires_at=now + erasure_flow.REQUEST_TTL,
    )
    db.add(req)
    await db.flush()
    run_now = await erasure_flow.schedule(db, req, confirmed_by_hash=who, decided_by=str(requester.id), role=initiated_by, now=now)
    await _record_member_decisions(db, target, handle=pseudonym(str(target.id)), outcome="erasure_scheduled",
                                   by=str(requester.id), via=initiated_by)
    await db.commit()
    if run_now:
        await erasure_flow.run_request(db, req)
        await db.refresh(req)
    when = req.execute_after.isoformat() if req.execute_after else None
    return {"data": {"request_id": req.id, "status": req.status, "execute_after": when, "pseudonym": pseudonym(str(target.id)),
                     "cancellable": req.status == erasure_flow.SCHEDULED, "irreversible": True}, "error": None}


async def _record_member_decisions(db: AsyncSession, target: User, *, handle: str, outcome: str, by: str, via: str) -> None:
    from app.models.decision import DecidedVia, DecisionKind
    from app.services.decisions import record_decision

    m = OrgMembership
    orgs = {str(o) for o in (await db.execute(select(m.org_id).where(m.user_id == str(target.id)))).scalars()}
    for org_id in sorted(orgs):
        await record_decision(
            db, org_id=org_id, kind=DecisionKind.MEMBER_CHANGE, target_type="member", target_id=handle, outcome=outcome,
            decided_via=DecidedVia.HUMAN, decided_by=by, after={"pseudonym": handle, "initiated_by": via},
        )


@router.post("/privacy/member-erasure")
async def erase_my_account(
    body: MemberErasureBody, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """A member asks for their own account and personal data to be erased."""
    return await _schedule_member(db, current_user, initiated_by="self", requester=current_user, confirmation=body.confirmation)


@router.post("/privacy/org/members/{user_id}/erasure")
async def erase_a_member(
    user_id: str, body: MemberErasureBody, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """The owner (or an admin, for lower roles) erases a member of the acting company who belongs to no other."""
    role = await acting_role(db, current_user) if current_user.org_id else None
    if role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Üye verisini silmek için owner veya admin rolü gerekli.")
    target = await db.get(User, user_id)
    ms = (await db.execute(select(OrgMembership).where(OrgMembership.user_id == user_id))).scalars().all()
    mine = next((x for x in ms if str(x.org_id) == str(current_user.org_id)), None)
    if target is None or mine is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    ensure_tenant(current_user, org_id=mine.org_id)
    if str(target.id) == str(current_user.id):
        raise HTTPException(status_code=409, detail="Kendi hesabınız için /privacy/member-erasure kullanın.")
    if len(ms) > 1:
        raise HTTPException(status_code=409, detail="Bu kişi başka şirketlerin de üyesi; kendi hesabını kendisi silebilir.")
    if role == "admin" and mine.role in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Bir admin, owner veya admin rolündeki üyenin verisini silemez.")
    return await _schedule_member(db, target, initiated_by="owner", requester=current_user, confirmation=body.confirmation)


@router.post("/privacy/member-erasure/{request_id}/cancel")
async def cancel_member_erasure(
    request_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Stop a scheduled member erasure: the person it is about, the person who asked, or a platform operator.

    The account stays usable during the cooling-off, so the person can change their mind themselves.
    """
    req = await db.get(OrgErasureRequest, request_id)
    if req is None or req.scope != "member":
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    uid = str(current_user.id)
    operator = is_platform_operator(current_user.email, get_settings().platform_operator_emails)
    if uid not in (req.target_user_id, req.requested_by_user_id) and not operator:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    target = await db.get(User, req.target_user_id) if req.target_user_id else None
    try:
        await erasure_flow.cancel(db, req, by_hash=hash_id("user", uid), decided_by=uid,
                                  role="platform_operator" if operator else req.initiated_by)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=f"Talep durumu: {exc}; iptal edilemez.") from exc
    if target is not None:
        await _record_member_decisions(db, target, handle=pseudonym(str(target.id)), outcome="erasure_cancelled",
                                       by=uid, via="operator" if operator else req.initiated_by)
    await db.commit()
    return {"data": {"request_id": req.id, "status": req.status}, "error": None}


@router.get("/privacy/erasure-requests")
async def list_erasure_requests(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Live erasure requests the caller may see: about their own account; owner/admin also the company's."""
    uid = str(current_user.id)
    mine = await _live_requests(db, target_user_id=uid) + await _live_requests(db, requested_by_user_id=uid)
    out = {r.id: r for r in mine}
    role = await acting_role(db, current_user) if current_user.org_id else None
    if role in ("owner", "admin"):
        org = (await db.execute(select(OrgErasureRequest).where(
            OrgErasureRequest.scope == "org", OrgErasureRequest.target_org_id == str(current_user.org_id),
            OrgErasureRequest.status.in_((erasure_flow.SCHEDULED, erasure_flow.PENDING))))).scalars()
        out.update({r.id: r for r in org})
    rows = [{
        "request_id": r.id, "scope": r.scope, "status": r.status, "initiated_by": r.initiated_by,
        "execute_after": r.execute_after.isoformat() if r.execute_after else None, "about_me": r.target_user_id == uid,
        "mode": r.mode, "cancellable": r.status in (erasure_flow.SCHEDULED, erasure_flow.PENDING),
    } for r in sorted(out.values(), key=lambda r: r.requested_at)]
    return {"data": {"requests": rows, "cooling_off_days": get_settings().erasure_cooling_off_days}, "error": None}

