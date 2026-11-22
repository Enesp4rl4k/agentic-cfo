"""KVKK Md. 7 / GDPR Art. 17 — erase a whole organisation, in two steps.

  POST /compliance/org-erasure/request               owner | admin of the org
  POST /compliance/org-erasure/{request_id}/confirm  owner of the org

Request records the intent and returns the phrase the owner must type back;
nothing is touched. Confirm re-checks the role, the organisation and the phrase,
then runs `app.services.org_erasure.erase_org` (one transaction, hash-chained
proof). The role is the caller's *membership* role in the organisation they are
acting in, not `users.role`: that column is one global value, and an accountant
who owns their own firm must not be able to erase a client's. An ordinary
member, analyst, viewer or accountant gets 403; another organisation's request
id gets 404 (`app.api.access.ensure_tenant`).

`mode` defaults to `anonymise`; `hard_delete` is opt-in. See the service module
docstring for the unresolved retention question (plan G19).
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.access import ensure_tenant
from app.api.auth import get_current_user
from app.config import get_settings
from app.database import get_db
from app.models.erasure_record import OrgErasureRequest
from app.models.organization import Organization, OrgMembership
from app.models.user import User
from app.services.org_erasure import erase_org, hash_id

router = APIRouter()
logger = logging.getLogger(__name__)

REQUEST_TTL = timedelta(days=7)
REQUESTERS = frozenset({"owner", "admin"})
CONFIRMERS = frozenset({"owner"})
NOT_FOUND = "Kayıt bulunamadı."


class OrgErasureBody(BaseModel):
    mode: Literal["anonymise", "hard_delete"] = "anonymise"


class OrgErasureConfirm(BaseModel):
    confirmation_phrase: str


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
    return {
        "data": {
            "request_id": req.id, "status": "pending", "mode": body.mode,
            "expires_at": req.expires_at.isoformat(),
            "confirmation_phrase": _phrase(org.slug),
            "irreversible": True,
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
    """Step 2: the owner confirms; the erasure runs. Idempotent."""
    await _require(db, current_user, CONFIRMERS)
    req = await db.get(OrgErasureRequest, request_id)
    if req is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    ensure_tenant(current_user, org_id=req.target_org_id)
    org_id = str(req.target_org_id)
    mode = req.mode
    _require_mode_allowed(mode)
    if req.status != "pending":
        raise HTTPException(status_code=409, detail=f"Talep durumu: {req.status}.")
    now = datetime.now(UTC)
    expires = req.expires_at if req.expires_at.tzinfo else req.expires_at.replace(tzinfo=UTC)
    if expires < now:
        req.status = "expired"
        await db.commit()
        raise HTTPException(status_code=409, detail="Talebin süresi doldu; yeniden talep edin.")
    org = await db.get(Organization, org_id)
    if org is None or body.confirmation_phrase.strip() != _phrase(org.slug):
        raise HTTPException(status_code=422, detail="Onay ifadesi eşleşmiyor.")

    confirmer = hash_id("user", str(current_user.id))
    result = await erase_org(
        db, org_id, mode=mode, requested_by_hash=req.requested_by_hash,
        confirmed_by_hash=confirmer,
    )
    await db.refresh(req)  # erase_org committed and cleared the raw ids
    req.status = "executed"
    req.confirmed_by_hash = confirmer
    req.confirmed_at = now
    req.record_id = result.record.id
    req.target_org_id = None
    req.requested_by_user_id = None
    await db.commit()
    logger.info("org erasure executed: request=%s mode=%s", req.id, req.mode)
    return {
        "data": {
            "request_id": req.id, "status": req.status, "mode": req.mode,
            "already_erased": result.already_erased,
            "record": {
                "seq": result.record.seq, "record_hash": result.record.record_hash,
                "org_hash": result.record.org_hash,
                "executed_at": result.record.executed_at.isoformat(),
                "counts": result.record.counts,
            },
        },
        "error": None,
    }


