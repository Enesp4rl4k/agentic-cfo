"""
Organization API — workspace management for multi-tenant SaaS.

POST   /api/v1/org/create          — create a new org (becomes owner)
GET    /api/v1/org/me              — get current user's org
PATCH  /api/v1/org/me              — update org settings (admin+)
GET    /api/v1/org/members         — list org members
DELETE /api/v1/org/members/{uid}   — remove a member (owner/admin)
POST   /api/v1/org/invite          — send invite (owner/admin)
POST   /api/v1/org/invite/accept   — accept invite via token
GET    /api/v1/org/invites         — list pending invites (admin+)
DELETE /api/v1/org/invites/{id}    — cancel invite (admin+)
"""
from __future__ import annotations

import logging
import re
import secrets
from datetime import datetime, timezone, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.organization import Organization, OrgInvite
from app.models.user import User, UserRole
from app.api.auth import get_current_user

router = APIRouter()
logger = logging.getLogger(__name__)

INVITE_EXPIRE_DAYS = 7


# ── Helpers ───────────────────────────────────────────────────────────────────

def _slugify(name: str) -> str:
    slug = name.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_-]+", "-", slug)
    slug = slug.strip("-")
    return slug[:80]


def _require_org(user: User) -> Organization:
    if not user.organization:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Henüz bir organizasyona üye değilsiniz. Önce bir workspace oluşturun.",
        )
    return user.organization


def _require_admin(user: User) -> Organization:
    org = _require_org(user)
    if user.role not in (UserRole.OWNER, UserRole.ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bu işlem için admin yetkisi gerekli.",
        )
    return org


def _require_owner(user: User) -> Organization:
    org = _require_org(user)
    if user.role != UserRole.OWNER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bu işlem için owner yetkisi gerekli.",
        )
    return org


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class CreateOrgRequest(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    slug: str | None = None  # auto-generated if omitted
    description: str | None = None


class UpdateOrgRequest(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    description: str | None = None
    logo_url: str | None = None


class InviteRequest(BaseModel):
    email: EmailStr
    role: str = "analyst"  # analyst | viewer | admin


class AcceptInviteRequest(BaseModel):
    token: str
    full_name: str | None = None
    password: str = Field(min_length=8)


def _org_dict(org: Organization) -> dict[str, Any]:
    return {
        "org_id":               org.id,
        "name":                 org.name,
        "slug":                 org.slug,
        "description":          org.description,
        "logo_url":             org.logo_url,
        "plan":                 org.plan,
        "max_members":          org.max_members,
        "max_jobs_per_month":   org.max_jobs_per_month,
        "is_active":            org.is_active,
        "created_at":           org.created_at.isoformat(),
    }


def _member_dict(u: User) -> dict[str, Any]:
    return {
        "user_id":      u.id,
        "email":        u.email,
        "full_name":    u.full_name,
        "role":         u.role,
        "is_active":    u.is_active,
        "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
        "joined_at":    u.created_at.isoformat(),
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/org/create", status_code=status.HTTP_201_CREATED)
async def create_org(
    body: CreateOrgRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Create a new organization. The calling user becomes the owner."""
    if current_user.org_id:
        raise HTTPException(
            status_code=400,
            detail="Zaten bir organizasyona üyesiniz. Yeni bir org oluşturmak için önce ayrılın.",
        )

    # Generate unique slug
    base_slug = body.slug or _slugify(body.name)
    slug = base_slug
    counter = 1
    while True:
        exists = await db.execute(select(Organization).where(Organization.slug == slug))
        if not exists.scalar_one_or_none():
            break
        slug = f"{base_slug}-{counter}"
        counter += 1

    org = Organization(
        name=body.name,
        slug=slug,
        description=body.description,
    )
    db.add(org)
    await db.flush()  # get org.id before commit

    # Set user as owner of the new org
    current_user.org_id = org.id
    current_user.role = UserRole.OWNER

    await db.commit()
    await db.refresh(org)
    await db.refresh(current_user)

    logger.info("Org created: %s (slug=%s) by user %s", org.name, org.slug, current_user.email)

    return {"data": _org_dict(org), "error": None}


@router.get("/org/me")
async def get_my_org(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get the current user's organization."""
    org = _require_org(current_user)
    # Count members
    result = await db.execute(
        select(User).where(User.org_id == org.id, User.is_active == True)
    )
    members = result.scalars().all()
    data = _org_dict(org)
    data["member_count"] = len(members)
    return {"data": data, "error": None}


@router.patch("/org/me")
async def update_org(
    body: UpdateOrgRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Update org settings. Requires admin role."""
    org = _require_admin(current_user)
    if body.name is not None:
        org.name = body.name
    if body.description is not None:
        org.description = body.description
    if body.logo_url is not None:
        org.logo_url = body.logo_url
    await db.commit()
    await db.refresh(org)
    return {"data": _org_dict(org), "error": None}


@router.get("/org/members")
async def list_members(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List all members of the current user's org."""
    org = _require_org(current_user)
    result = await db.execute(
        select(User).where(User.org_id == org.id).order_by(User.created_at)
    )
    members = result.scalars().all()
    return {
        "data": {
            "org_id":  org.id,
            "members": [_member_dict(m) for m in members],
            "total":   len(members),
        },
        "error": None,
    }


@router.delete("/org/members/{user_id}")
async def remove_member(
    user_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Remove a member from the org. Owners can remove anyone; admins can remove analysts/viewers."""
    org = _require_admin(current_user)

    if user_id == current_user.id:
        raise HTTPException(400, detail="Kendinizi org'dan çıkaramazsınız.")

    target = await db.get(User, user_id)
    if not target or target.org_id != org.id:
        raise HTTPException(404, detail="Kullanıcı bu org'da bulunamadı.")

    # Admins cannot remove other admins or owners
    if current_user.role == UserRole.ADMIN and target.role in (UserRole.OWNER, UserRole.ADMIN):
        raise HTTPException(403, detail="Admin, başka bir admin veya owner'ı çıkaramaz.")

    target.org_id = None
    target.role = UserRole.ANALYST  # reset to default
    await db.commit()

    logger.info("User %s removed from org %s by %s", target.email, org.id, current_user.email)
    return {"data": {"removed": True}, "error": None}


@router.post("/org/invite", status_code=status.HTTP_201_CREATED)
async def invite_member(
    body: InviteRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Invite someone to join the org by email."""
    org = _require_admin(current_user)

    # Check member limit
    result = await db.execute(
        select(User).where(User.org_id == org.id, User.is_active == True)
    )
    count = len(result.scalars().all())
    if count >= org.max_members:
        raise HTTPException(400, detail=f"Üye limiti doldu ({org.max_members}).")

    # Invalidate previous pending invites for same email+org
    old = await db.execute(
        select(OrgInvite).where(
            OrgInvite.org_id == org.id,
            OrgInvite.email == str(body.email),
            OrgInvite.accepted == False,
        )
    )
    for inv in old.scalars().all():
        await db.delete(inv)

    invite = OrgInvite(
        org_id=org.id,
        email=str(body.email),
        role=body.role,
        token=secrets.token_hex(32),
        expires_at=datetime.now(timezone.utc) + timedelta(days=INVITE_EXPIRE_DAYS),
    )
    db.add(invite)
    await db.commit()
    await db.refresh(invite)

    logger.info("Invite sent: %s → %s (role=%s)", org.name, body.email, body.role)

    # TODO: send email via Resend/SendGrid — token available in invite.token
    return {
        "data": {
            "invite_id":  invite.id,
            "email":      invite.email,
            "role":       invite.role,
            "token":      invite.token,  # remove from response in prod (send via email only)
            "expires_at": invite.expires_at.isoformat(),
        },
        "error": None,
    }


@router.post("/org/invite/accept", status_code=status.HTTP_201_CREATED)
async def accept_invite(
    body: AcceptInviteRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Accept an org invite. Creates user account if email not yet registered,
    otherwise joins existing user to the org.
    """
    from app.services.auth import hash_password, create_access_token, create_refresh_token

    result = await db.execute(
        select(OrgInvite).where(OrgInvite.token == body.token, OrgInvite.accepted == False)
    )
    invite = result.scalar_one_or_none()
    if not invite:
        raise HTTPException(400, detail="Geçersiz veya süresi dolmuş davet bağlantısı.")

    if invite.expires_at < datetime.now(timezone.utc):
        raise HTTPException(400, detail="Davet bağlantısının süresi dolmuş.")

    # Find or create user
    result = await db.execute(select(User).where(User.email == invite.email))
    user = result.scalar_one_or_none()

    if user:
        if user.org_id and user.org_id != invite.org_id:
            raise HTTPException(400, detail="Zaten başka bir organizasyona üyesiniz.")
    else:
        user = User(
            email=invite.email,
            hashed_password=hash_password(body.password),
            full_name=body.full_name,
            role=invite.role,
        )
        db.add(user)
        await db.flush()

    user.org_id = invite.org_id
    user.role = invite.role
    invite.accepted = True

    await db.commit()
    await db.refresh(user)

    access  = create_access_token(user.id, user.email, user.role)
    refresh = create_refresh_token(user.id)

    logger.info("Invite accepted: %s joined org %s", user.email, invite.org_id)

    return {
        "data": {
            "access_token":  access,
            "refresh_token": refresh,
            "token_type":    "bearer",
            "expires_in":    1800,
            "user": {
                "user_id":  user.id,
                "email":    user.email,
                "role":     user.role,
                "org_id":   user.org_id,
            },
        },
        "error": None,
    }


@router.get("/org/invites")
async def list_invites(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List pending invites for the org."""
    org = _require_admin(current_user)
    result = await db.execute(
        select(OrgInvite)
        .where(OrgInvite.org_id == org.id, OrgInvite.accepted == False)
        .order_by(OrgInvite.created_at.desc())
    )
    invites = result.scalars().all()
    return {
        "data": [
            {
                "invite_id":  i.id,
                "email":      i.email,
                "role":       i.role,
                "expires_at": i.expires_at.isoformat(),
                "created_at": i.created_at.isoformat(),
            }
            for i in invites
        ],
        "error": None,
    }


@router.delete("/org/invites/{invite_id}")
async def cancel_invite(
    invite_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Cancel a pending invite."""
    org = _require_admin(current_user)
    result = await db.execute(
        select(OrgInvite).where(OrgInvite.id == invite_id, OrgInvite.org_id == org.id)
    )
    invite = result.scalar_one_or_none()
    if not invite:
        raise HTTPException(404, detail="Davet bulunamadı.")
    await db.delete(invite)
    await db.commit()
    return {"data": {"cancelled": True}, "error": None}
