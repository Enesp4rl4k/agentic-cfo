"""KVKK Md. 7 / GDPR Art. 17 — erase a whole organisation: request, confirm, cooling-off, cancel.

  POST /compliance/org-erasure/request               owner | admin of the org
  POST /compliance/org-erasure/{request_id}/confirm  owner of the org
  POST /compliance/org-erasure/{request_id}/cancel   owner of the org, or a platform operator
  POST /compliance/operator/org-erasure              platform operator, on a verified request

Request records the intent and returns the phrase the owner must type back; nothing is touched. Confirm re-checks
the role, the organisation and the phrase and SCHEDULES the erasure: the destructive step runs after the cooling-off
window (ERASURE_COOLING_OFF_DAYS, default 7) in the scheduler (`app.services.privacy.erasure_flow.execute_due`), and
the owner can cancel until then. With the window set to 0 confirm runs it at once. The step itself is
`app.services.org_erasure.erase_org` (one transaction, hash-chained proof). Every step leaves an `erasure` decision
record. The role is the caller's *membership* role in the organisation they are acting in, not `users.role`: that
column is one global value, and an accountant who owns their own firm must not be able to erase a client's. An
ordinary member, analyst, viewer or accountant gets 403; another organisation's request id gets 404
(`app.api.access.ensure_tenant`).

`mode` defaults to `anonymise`; `hard_delete` is opt-in. See the service module docstring for the unresolved
retention question (plan G19).
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.access import ensure_tenant, is_platform_operator, require_platform_operator
from app.api.auth import get_current_user
from app.config import get_settings
from app.database import get_db
from app.models.erasure_record import OrgErasureRecord, OrgErasureRequest
from app.models.in_app_notification import InAppNotification
from app.models.organization import Organization, OrgMembership
from app.models.user import User
from app.services.org_erasure import hash_id
from app.services.privacy import erasure_flow

router = APIRouter()
logger = logging.getLogger(__name__)

REQUEST_TTL = erasure_flow.REQUEST_TTL
REQUESTERS = frozenset({"owner", "admin"})
CONFIRMERS = frozenset({"owner"})
NOT_FOUND = "Kayıt bulunamadı."


class OrgErasureBody(BaseModel):
    mode: Literal["anonymise", "hard_delete"] = "anonymise"


class OrgErasureConfirm(BaseModel):
    confirmation_phrase: str


class OperatorErasureBody(BaseModel):
    org_id: str
    mode: Literal["anonymise", "hard_delete"] = "anonymise"
    # The ticket or case number under which the data subject's identity and authority were verified; never a name.
    verification_ref: str = Field(min_length=3, max_length=100)


def _require_mode_allowed(mode: str) -> None:
    """`hard_delete` is off until ORG_ERASURE_HARD_DELETE_ENABLED is set (plan G19)."""
    if mode == "hard_delete" and not get_settings().org_erasure_hard_delete_enabled:
        raise HTTPException(
            status_code=422,
            detail="hard_delete bu sunucuda etkin değil (ORG_ERASURE_HARD_DELETE_ENABLED); "
                   "yalnızca 'anonymise' kullanılabilir.",
        )


def _phrase(slug: str) -> str:
    return f"ERASE {slug}"


async def _require(db: AsyncSession, user: User, allowed: frozenset[str]) -> str:
    role = None
    if user.org_id:
        role = (await db.execute(
            select(OrgMembership.role).where(
                OrgMembership.user_id == str(user.id), OrgMembership.org_id == str(user.org_id)
            )
        )).scalar_one_or_none()
    if role not in allowed:
        raise HTTPException(
            status_code=403,
            detail=f"Organizasyon verisini silmek için '{'/'.join(sorted(allowed))}' rolü gerekli.",
        )
    return str(user.org_id)


def _scheduled(req: OrgErasureRequest) -> dict[str, Any]:
    when = req.execute_after.isoformat() if req.execute_after else None
    return {
        "data": {
            "request_id": req.id, "status": req.status, "mode": req.mode, "execute_after": when,
            "cancellable": True, "irreversible": True,
            "note": "Nothing has been erased. The erasure runs when the cooling-off ends; the owner can cancel until then.",
        },
        "error": None,
    }


@router.post("/compliance/org-erasure/request")
async def request_org_erasure(
    body: OrgErasureBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Step 1: record the request. Deletes nothing."""
    org_id = await _require(db, current_user, REQUESTERS)
    _require_mode_allowed(body.mode)
    org = await db.get(Organization, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    now = datetime.now(UTC)
    req = OrgErasureRequest(
        target_org_id=org_id, org_hash=hash_id("org", org_id), mode=body.mode, status="pending",
        requested_by_user_id=str(current_user.id),
        requested_by_hash=hash_id("user", str(current_user.id)),
        requested_at=now, expires_at=now + REQUEST_TTL,
    )
    db.add(req)
    await db.commit()
    logger.info("org erasure requested: request=%s mode=%s", req.id, body.mode)
    window = erasure_flow.cooling_off("owner")
    return {
        "data": {
            "request_id": req.id, "status": "pending", "mode": body.mode,
            "expires_at": req.expires_at.isoformat(),
            "confirmation_phrase": _phrase(org.slug),
            "irreversible": True,
            "cooling_off_days": window.days,
            "note": "The organisation owner must confirm with the phrase. Nothing is erased yet.",
        },
        "error": None,
    }


@router.post("/compliance/org-erasure/{request_id}/confirm")
async def confirm_org_erasure(
    request_id: str,
    body: OrgErasureConfirm,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Step 2: the owner confirms; the erasure is scheduled (or runs now when there is no cooling-off)."""
    await _require(db, current_user, CONFIRMERS)
    req = await db.get(OrgErasureRequest, request_id)
    if req is None or req.scope != "org":
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    ensure_tenant(current_user, org_id=req.target_org_id)
    _require_mode_allowed(req.mode)
    if req.status != erasure_flow.PENDING:
        raise HTTPException(status_code=409, detail=f"Talep durumu: {req.status}.")
    now = datetime.now(UTC)
    expires = req.expires_at if req.expires_at.tzinfo else req.expires_at.replace(tzinfo=UTC)
    if expires < now:
        req.status = erasure_flow.EXPIRED
        await db.commit()
        raise HTTPException(status_code=409, detail="Talebin süresi doldu; yeniden talep edin.")
    org = await db.get(Organization, str(req.target_org_id))
    if org is None or body.confirmation_phrase.strip() != _phrase(org.slug):
        raise HTTPException(status_code=422, detail="Onay ifadesi eşleşmiyor.")

    run_now = await erasure_flow.schedule(
        db, req, confirmed_by_hash=hash_id("user", str(current_user.id)), decided_by=str(current_user.id),
        role="owner", now=now)
    await db.commit()
    if not run_now:
        return _scheduled(req)
    outcome = await erasure_flow.run_request(db, req)
    if outcome.get("claimed") is False:  # cancelled or taken by the executor between confirm and run
        raise HTTPException(status_code=409, detail=f"Talep durumu: {outcome['status']}.")
    await db.refresh(req)
    record = await db.get(OrgErasureRecord, req.record_id) if req.record_id else None
    logger.info("org erasure executed: request=%s mode=%s", req.id, req.mode)
    return {
        "data": {
            "request_id": req.id, "status": req.status, "mode": req.mode,
            "already_erased": bool(outcome.get("already_erased")),
            "record": None if record is None else {
                "seq": record.seq, "record_hash": record.record_hash, "org_hash": record.org_hash,
                "executed_at": record.executed_at.isoformat(), "counts": record.counts,
            },
        },
        "error": None,
    }


def _cannot_cancel(status: str) -> str:
    if status == erasure_flow.EXECUTING:
        return "Silme işlemi şu anda çalışıyor; iptal edilemez."
    return f"Talep durumu: {status}; iptal edilemez."


@router.post("/compliance/org-erasure/{request_id}/cancel")
async def cancel_org_erasure(
    request_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Stop a pending or scheduled erasure: the organisation's owner, or a platform operator."""
    req = await db.get(OrgErasureRequest, request_id)
    operator = is_platform_operator(current_user.email, get_settings().platform_operator_emails)
    if req is None or req.scope != "org":
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    if not operator:
        await _require(db, current_user, CONFIRMERS)
        ensure_tenant(current_user, org_id=req.target_org_id)
    try:
        await erasure_flow.cancel(
            db, req, by_hash=hash_id("user", str(current_user.id)), decided_by=str(current_user.id),
            role="platform_operator" if operator else "owner")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=_cannot_cancel(str(exc))) from exc
    await db.commit()
    return {"data": {"request_id": req.id, "status": req.status}, "error": None}


@router.post("/compliance/operator/org-erasure")
async def operator_schedule_org_erasure(
    body: OperatorErasureBody,
    operator: User = Depends(require_platform_operator),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """The platform operator schedules an erasure on a verified request. The cooling-off is never skipped: the
    organisation's owner is told in the product and can cancel until it ends."""
    _require_mode_allowed(body.mode)
    org = await db.get(Organization, body.org_id)
    if org is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    now = datetime.now(UTC)
    who = hash_id("user", str(operator.id))
    req = OrgErasureRequest(
        target_org_id=body.org_id, org_hash=hash_id("org", body.org_id), mode=body.mode, status=erasure_flow.PENDING,
        requested_by_user_id=str(operator.id), requested_by_hash=who, requested_at=now, expires_at=now + REQUEST_TTL,
        initiated_by="operator", verification_ref=body.verification_ref.strip(),
    )
    db.add(req)
    await db.flush()
    await erasure_flow.schedule(
        db, req, confirmed_by_hash=who, decided_by=str(operator.id), role="platform_operator", now=now)
    db.add(InAppNotification(
        org_id=body.org_id, level="warning", domain="privacy", source="org_erasure", action="escalate",
        message="Şirket verisinin silinmesi platform operatörü tarafından planlandı; "
                f"{req.execute_after:%Y-%m-%d %H:%M} UTC'den sonra yapılır. Sahip, o zamana kadar "
                "Ayarlar > Veri ve gizlilik bölümünden iptal edebilir.",
    ))
    await db.commit()
    logger.info("org erasure scheduled by operator: request=%s mode=%s", req.id, body.mode)
    return _scheduled(req)
