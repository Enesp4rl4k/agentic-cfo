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
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import _bearer, get_current_user
from app.core.email_address import normalize_email
from app.database import get_db
from app.models.decision import DecidedVia, DecisionKind
from app.models.organization import Organization, OrgInvite, OrgMembership
from app.models.password_reset import PasswordResetToken
from app.models.user import User, UserRole
from app.services import email_verification
from app.services.acting_role import acting_role
from app.services.decisions import record_decision
from app.services.org_identity_decision import identity_view, record_identity_change
from app.services.secret_tokens import hash_token, new_token

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


# `get_current_user` serves users out of a 60-second cache, so `current_user` is
# routinely an ORM instance whose session has already closed. Touching
# `user.organization` then raises DetachedInstanceError instead of loading the
# org, and mutating the instance raises "not persistent within this Session" —
# which is why creating a workspace failed for every request after the first.
# Load the org through the request's own session, and mutate only instances
# fetched from it. Same rule deps_regional.py already follows.

async def _load_org(user: User, db: AsyncSession) -> Organization:
    org = await db.get(Organization, str(user.org_id)) if user.org_id else None
    if org is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Henüz bir organizasyona üye değilsiniz. Önce bir workspace oluşturun.",
        )
    return org


async def _require_org(user: User, db: AsyncSession) -> Organization:
    return await _load_org(user, db)


async def _require_admin(user: User, db: AsyncSession) -> Organization:
    org = await _load_org(user, db)
    if await acting_role(db, user) not in (UserRole.OWNER, UserRole.ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bu işlem için admin yetkisi gerekli.",
        )
    return org


async def _require_owner(user: User, db: AsyncSession) -> Organization:
    org = await _load_org(user, db)
    if await acting_role(db, user) != UserRole.OWNER:
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
    # Turkish companies are who this is built for. Every organisation used to
    # be created as US/USD with no regional pack, so a firm that had just
    # signed up got 404 from e-Fatura and muhasebe and US tax rates.
    country_code: str = Field(default="TR", min_length=2, max_length=2)


class UpdateOrgRequest(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    description: str | None = None
    logo_url: str | None = None
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    base_currency: str | None = Field(default=None, min_length=3, max_length=3)
    locale: str | None = Field(default=None, min_length=2, max_length=16)
    regional_packs: list[str] | None = None
    focus_mode: bool | None = None
    vkn: str | None = Field(default=None, max_length=20)
    legal_title: str | None = Field(default=None, max_length=200)


class InviteRequest(BaseModel):
    email: EmailStr
    # An enum, not a string: a junk value used to be stored and then raised
    # ValueError (500) when the invite was accepted. Pydantic answers 422.
    role: UserRole = UserRole.ANALYST


# Who may hand out which role. Only an owner makes an owner or an admin; an admin
# may invite anything below them. `smmm` is invitable: a company adds its own
# accountant that way (the accountant who adds a *client* gets `smmm` in it
# through /smmm/clients instead).
_INVITER_MAY_GRANT: dict[str, frozenset[str]] = {
    # One owner per company: an owner cannot make another owner. Transferring ownership is a separate,
    # explicit action (not built yet).
    "owner": frozenset({"admin", "cfo", "smmm", "analyst", "viewer"}),
    "admin": frozenset({"cfo", "smmm", "analyst", "viewer"}),
}


class AcceptInviteRequest(BaseModel):
    token: str
    full_name: str | None = None
    # Needed to create an account, and to prove an existing one when the caller has no session of it.
    password: str | None = Field(default=None, min_length=8)


def _org_dict(org: Organization) -> dict[str, Any]:
    from app.services.regional.packs import normalize_packs

    return {
        "org_id":               org.id,
        "name":                 org.name,
        "slug":                 org.slug,
        "description":          org.description,
        "logo_url":             org.logo_url,
        "country_code":         getattr(org, "country_code", None) or "US",
        "base_currency":        getattr(org, "base_currency", None) or "USD",
        "vkn":                 getattr(org, "vkn", None),
        "legal_title":         getattr(org, "legal_title", None),
        "locale":               getattr(org, "locale", None) or "en-US",
        "regional_packs":       normalize_packs(getattr(org, "regional_packs", None)),
        "focus_mode":           bool(org.focus_mode),
        "size_profile":         org.size_profile,
        "plan":                 org.plan,
        "max_members":          org.max_members,
        "max_jobs_per_month":   org.max_jobs_per_month,
        "is_active":            org.is_active,
        "created_at":           org.created_at.isoformat(),
    }


async def _base_fields(db: AsyncSession, org: Organization) -> dict[str, Any]:
    """How this organisation's money is labelled: `base_currency` above is only the stored column (its default
    is USD), so screens format with `effective_currency` (`core/currency_totals.effective_base`)."""
    from app.services.ledger_base import effective_base_of

    eb = await effective_base_of(db, str(org.id))
    return {
        "base_currency_confirmed": org.base_currency_confirmed_at is not None,
        "effective_currency": eb.run_currency,
        "base_state": eb.state,
    }


async def _org_members(db: AsyncSession, org_id: str) -> list[tuple[User, str]]:
    """Members of an organisation with their role *in it*, oldest first.

    Listed by membership rows, not `users.org_id`: that column is only the
    organisation a user is acting in, so an accountant switched into another
    client would vanish from this one while `require_smmm` still counts them.
    A user with `users.org_id` here and no membership row (older than migration
    050) is included with `users.role`.
    """
    rows = (
        await db.execute(
            select(User, OrgMembership.role)
            .join(OrgMembership, OrgMembership.user_id == User.id)
            .where(OrgMembership.org_id == org_id)
        )
    ).all()
    members: dict[str, tuple[User, str]] = {str(u.id): (u, str(r)) for u, r in rows}
    legacy = (await db.execute(select(User).where(User.org_id == org_id))).scalars().all()
    for u in legacy:
        members.setdefault(str(u.id), (u, str(getattr(u.role, "value", u.role))))
    return sorted(members.values(), key=lambda m: m[0].created_at)


def _member_dict(u: User, role: str) -> dict[str, Any]:
    return {
        "user_id":      u.id,
        "email":        u.email,
        "full_name":    u.full_name,
        "role":         role,
        "is_active":    u.is_active,
        "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
        "joined_at":    u.created_at.isoformat(),
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────

def _regional_defaults(country_code: str) -> dict[str, Any]:
    cc = country_code.upper()
    if cc == "TR":
        return {"country_code": "TR", "base_currency": "TRY", "locale": "tr-TR", "regional_packs": ["tr"]}
    return {"country_code": cc, "base_currency": "USD", "locale": "en-US", "regional_packs": []}


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
    if body.slug and body.slug.lower().startswith("demo-"):
        raise HTTPException(status_code=422, detail="'demo-' öneki ayrılmıştır; başka bir kısa ad seçin.")
    base_slug = body.slug or _slugify(body.name)
    if base_slug.startswith("demo-"):
        base_slug = f"org-{base_slug}"  # the demo prefix is reserved for guest workspaces
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
        **_regional_defaults(body.country_code),
    )
    db.add(org)
    await db.flush()  # get org.id before commit

    # Set user as owner of the new org. `current_user` may be a cached instance
    # from a closed session — mutating it raises "not persistent within this
    # Session", so re-load the row through this request's session first.
    user_row = await db.get(User, str(current_user.id))
    if user_row is None:  # pragma: no cover - the token resolved a moment ago
        raise HTTPException(status_code=401, detail="Kullanıcı bulunamadı.")
    user_row.org_id = org.id
    user_row.role = UserRole.OWNER
    from app.services.org_membership import ensure_membership

    await ensure_membership(
        db, user_id=str(user_row.id), org_id=str(org.id), role=UserRole.OWNER.value
    )

    await db.commit()
    await db.refresh(org)


    logger.info("Org created: %s (slug=%s) by user %s", org.name, org.slug, current_user.email)

    return {"data": _org_dict(org), "error": None}


@router.get("/org/me")
async def get_my_org(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get the current user's organization."""
    org = await _require_org(current_user, db)
    # Count members
    members = [u for u, _ in await _org_members(db, str(org.id)) if u.is_active]
    data = {**_org_dict(org), **await _base_fields(db, org)}
    data["member_count"] = len(members)
    # Whether an active accountant (smmm) belongs to the company, so the screens can adapt, and the
    # defaults the confirmed size profile sets (a starting point, never a lock).
    from app.services.accountant import has_active_smmm
    from app.services.size_profile import profile_defaults

    data["has_smmm"] = await has_active_smmm(db, str(org.id))
    data["briefing_to_smmm"] = bool(org.briefing_to_smmm)
    data["profile_defaults"] = profile_defaults(org.size_profile)
    return {"data": data, "error": None}


@router.patch("/org/me")
async def update_org(
    body: UpdateOrgRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Update org settings. Requires admin role."""
    org = await _require_admin(current_user, db)
    before = identity_view(org)
    if body.name is not None:
        org.name = body.name
    if body.description is not None:
        org.description = body.description
    if body.logo_url is not None:
        org.logo_url = body.logo_url
    if body.country_code is not None:
        org.country_code = body.country_code.upper()
    if body.base_currency is not None and body.base_currency.upper() != (org.base_currency or "").upper():
        # The company currency decides how every currency-less document is read, so changing it is a
        # decision: POST /org/base-currency (owner or admin, recorded with before and after). The
        # same value as stored is ignored, so a form that always sends it still saves.
        raise HTTPException(
            status_code=422,
            detail="base_currency yalnızca POST /org/base-currency ile değiştirilir (onay kaydı tutulur).",
        )
    if body.locale is not None:
        org.locale = body.locale
    if body.regional_packs is not None:
        from app.services.regional.packs import normalize_packs

        org.regional_packs = normalize_packs(body.regional_packs)
    if body.focus_mode is not None:
        org.focus_mode = body.focus_mode
        org.focus_mode_explicit = True  # a person chose; a size profile never overrides it
    if body.vkn is not None:
        from app.services.org_identity import normalize, vkn_gecerli

        if body.vkn.strip() == "":
            org.vkn = None
        elif not vkn_gecerli(body.vkn):
            # One wrong digit would turn every invoice's direction around.
            raise HTTPException(
                status_code=422, detail="Geçersiz VKN/TCKN (10 ya da 11 hane, sağlama toplamı tutmuyor)."
            )
        else:
            org.vkn = normalize(body.vkn)
    if body.legal_title is not None:
        org.legal_title = body.legal_title.strip() or None
    await record_identity_change(db, org, current_user, before)
    await db.commit()
    await db.refresh(org)
    return {"data": {**_org_dict(org), **await _base_fields(db, org)}, "error": None}


@router.get("/org/me/tax-rates")
async def get_org_tax_rates(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Pack-aware tax rate table for the tax lens."""
    from app.services.regional.packs import normalize_packs
    from app.services.regional.tax import tax_rates_for_org

    org = await _require_org(current_user, db)
    data = tax_rates_for_org(
        country_code=getattr(org, "country_code", None) or "US",
        regional_packs=normalize_packs(getattr(org, "regional_packs", None)),
    )
    return {"data": data, "error": None}


@router.get("/org/members")
async def list_members(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List all members of the current user's org."""
    org = await _require_org(current_user, db)
    members = await _org_members(db, str(org.id))
    return {
        "data": {
            "org_id":  org.id,
            "members": [_member_dict(m, role) for m, role in members],
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
    org = await _require_admin(current_user, db)

    if user_id == current_user.id:
        raise HTTPException(400, detail="Kendinizi org'dan çıkaramazsınız.")

    target = await db.get(User, user_id)
    membership = (
        await db.execute(
            select(OrgMembership).where(
                OrgMembership.user_id == user_id, OrgMembership.org_id == str(org.id)
            )
        )
    ).scalar_one_or_none()
    # A member is whoever holds a membership row here (an accountant switched
    # into another client has `users.org_id` elsewhere), or a legacy user with
    # no row whose acting organisation this is.
    if not target or (membership is None and str(target.org_id) != str(org.id)):
        raise HTTPException(404, detail="Kullanıcı bu org'da bulunamadı.")

    # Admins cannot remove other admins or owners
    target_role = membership.role if membership is not None else str(getattr(target.role, "value", target.role))
    if await acting_role(db, current_user) == UserRole.ADMIN and target_role in (UserRole.OWNER, UserRole.ADMIN):
        raise HTTPException(403, detail="Admin, başka bir admin veya owner'ı çıkaramaz.")

    from app.services.org_membership import drop_membership

    await record_decision(
        db, org_id=str(org.id), kind=DecisionKind.MEMBER_CHANGE, target_type="org_membership",
        target_id=str(membership.id) if membership is not None else str(target.id), outcome="removed",
        decided_via=DecidedVia.HUMAN, decided_by=str(current_user.id),
        evidence_refs=[{"type": "user", "id": str(target.id)}],
        before={"role": target_role}, after=None,
    )
    await drop_membership(db, user_id=str(target.id), org_id=str(org.id))
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
    org = await _require_admin(current_user, db)

    inviter_role = str(await acting_role(db, current_user))
    if body.role.value not in _INVITER_MAY_GRANT.get(inviter_role, frozenset()):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Şirketin tek bir sahibi (owner) olur; davetle ikinci bir owner eklenemez."
                if body.role.value == "owner"
                else f"'{body.role.value}' rolünü bu rolünüzle veremezsiniz (admin rolünü yalnızca owner verir)."
            ),
        )

    # Check member limit
    count = len([u for u, _ in await _org_members(db, str(org.id)) if u.is_active])
    if count >= org.max_members:
        raise HTTPException(400, detail=f"Üye limiti doldu ({org.max_members}).")

    # Invalidate previous pending invites for same email+org
    old = await db.execute(
        select(OrgInvite).where(
            OrgInvite.org_id == org.id,
            OrgInvite.email == normalize_email(str(body.email)),
            OrgInvite.accepted.is_(False),
        )
    )
    for inv in old.scalars().all():
        await db.delete(inv)

    raw_token, token_digest = new_token()
    invite = OrgInvite(
        org_id=org.id,
        email=normalize_email(str(body.email)),
        role=body.role.value,
        token_hash=token_digest,
        expires_at=datetime.now(UTC) + timedelta(days=INVITE_EXPIRE_DAYS),
    )
    db.add(invite)
    await db.flush()
    # The e-mail is an outbox row of the immediate class (no release; the link is the only content),
    # written in the invitation's own transaction and delivered, retried and recorded by the outbox
    # sender: a failure shows on the row, never silently.
    from app.config import get_settings
    from app.services import outbox, outbox_immediate

    frontend = get_settings().frontend_url.rstrip("/")
    await outbox_immediate.enqueue_org_invite(
        db, invite_id=str(invite.id), org_id=str(org.id), email=invite.email, org_name=org.name or "",
        role=invite.role, accept_url=f"{frontend}/auth/accept-invite?token={raw_token}",
        expires_at=invite.expires_at,
    )
    await record_decision(
        db, org_id=str(org.id), kind=DecisionKind.MEMBER_CHANGE, target_type="org_invite",
        target_id=str(invite.id), outcome="invited", decided_via=DecidedVia.HUMAN, decided_by=str(current_user.id),
        after={"role": invite.role, "email": invite.email},
    )
    await db.commit()
    await db.refresh(invite)

    outbox.kick()
    email_sent = True  # handed to the outbox; its delivery is recorded there
    logger.info("Invite queued: %s → %s (role=%s)", org.name, body.email, body.role.value)

    return {
        "data": {
            "invite_id":  invite.id,
            "email":      invite.email,
            "role":       invite.role,
            "expires_at": invite.expires_at.isoformat(),
            "email_sent": bool(email_sent),
        },
        "error": None,
    }


def _utc(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _invite_state(invite: OrgInvite | None) -> str:
    """`valid`, `used` (already accepted), `expired`, or `unknown` (no such invitation, or cancelled)."""
    if invite is None:
        return "unknown"
    if invite.accepted:
        return "used"
    if _utc(invite.expires_at) < datetime.now(UTC):
        return "expired"
    return "valid"


class PreviewInviteRequest(BaseModel):
    token: str = Field(min_length=8, max_length=128)


@router.post("/org/invite/preview")
async def preview_invite(
    body: PreviewInviteRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """What the invitation page needs before anyone signs in: whose invitation, in which role, in what state.

    The token is the secret (64 random hex characters, e-mailed to the invitee); whoever holds it
    may read this. It is a POST so the token is in the body, not in a URL that access logs and proxies
    keep. It says whether the invited address already has an account, so the page asks for
    a password to sign in or to create one.
    """
    invite = (await db.execute(select(OrgInvite).where(OrgInvite.token_hash == hash_token(body.token)))).scalar_one_or_none()
    state = _invite_state(invite)
    if invite is None:
        return {"data": {"state": state}, "error": None}
    org = await db.get(Organization, str(invite.org_id))
    account = (await db.execute(select(User.id).where(User.email == normalize_email(invite.email)))).first()
    return {
        "data": {
            "state": state,
            "email": invite.email,
            "role": invite.role,
            "org_name": org.name if org else None,
            "account_exists": account is not None,
            "expires_at": _utc(invite.expires_at).isoformat(),
        },
        "error": None,
    }


@router.post("/org/invite/accept", status_code=status.HTTP_201_CREATED)
async def accept_invite(
    body: AcceptInviteRequest,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Accept an org invite. Creates the account if the address has none; otherwise adds this
    organisation to the existing account.

    A person may belong to several organisations (an accountant to every client): accepting adds a
    membership and never disturbs the ones they have, nor the organisation they are acting in. Only
    someone with no organisation yet starts acting in this one. An existing account proves it is
    theirs, with its password or a session of the invited address: the token alone is not enough to
    sign in as somebody who already has an account.
    """
    from app.services.auth import create_access_token, create_refresh_token, hash_password

    result = await db.execute(select(OrgInvite).where(OrgInvite.token_hash == hash_token(body.token)))
    invite = result.scalar_one_or_none()
    state = _invite_state(invite)
    if invite is None or state == "unknown":
        raise HTTPException(400, detail="Geçersiz veya süresi dolmuş davet bağlantısı.")
    if state == "used":
        raise HTTPException(400, detail="Bu davet daha önce kullanılmış.")
    if state == "expired":
        raise HTTPException(400, detail="Davet bağlantısının süresi dolmuş.")
    if invite.role not in {r.value for r in UserRole}:
        # An invite stored before the role was validated.
        raise HTTPException(400, detail="Davetteki rol geçersiz; yeni bir davet isteyin.")

    # Find or create user
    result = await db.execute(select(User).where(User.email == normalize_email(invite.email)))
    user = result.scalar_one_or_none()

    async def claim() -> None:
        # Single use, decided by the database: of two simultaneous accepts only the one whose UPDATE flips
        # `accepted` goes on; the other changes nothing and is refused. Done after the caller has proved
        # who they are (a wrong password must not burn the token) and before anything else is written.
        claimed = await db.execute(
            update(OrgInvite).where(OrgInvite.id == invite.id, OrgInvite.accepted.is_(False)).values(accepted=True)
        )
        if claimed.rowcount != 1:
            await db.rollback()
            raise HTTPException(400, detail="Bu davet daha önce kullanılmış.")

    now = datetime.now(UTC)
    # An account at this address that nobody has verified (someone may have registered the invitee's
    # address in advance, to lock them out). The invitation was e-mailed to this address, so holding its
    # token is the proof of ownership: the account is taken over in place. Its password becomes the one
    # given here, its sessions end, and nothing else the squatter set (name, API key, SSO link,
    # memberships, organisation) is kept; it signs in nowhere before this, so it holds no data.
    squatter = (
        user is not None and user.email_verified_at is None and email_verification.required()
    )

    if user is not None and squatter:
        if not user.is_active:
            raise HTTPException(403, detail="Hesabınız devre dışı bırakılmış.")
        if not body.password:
            raise HTTPException(422, detail="Hesabı devralmak için en az 8 karakterlik bir şifre gerekli.")
        await claim()
        await db.execute(delete(OrgMembership).where(OrgMembership.user_id == str(user.id)))
        user.hashed_password = hash_password(body.password)
        user.full_name = body.full_name
        user.api_key = None
        user.sso_provider = None
        user.sso_id = None
        user.token_version = (user.token_version or 0) + 1
        user.password_changed_at = now
        user.org_id = invite.org_id
        user.role = invite.role
        user.email_verified_at = now
        await db.execute(
            update(PasswordResetToken)
            .where(PasswordResetToken.user_id == str(user.id), PasswordResetToken.used_at.is_(None))
            .values(used_at=now).execution_options(synchronize_session=False)
        )
        await email_verification.mark_verified(db, str(user.id))
    elif user is not None:
        if not user.is_active:
            raise HTTPException(403, detail="Hesabınız devre dışı bırakılmış.")
        if not _proves_account(credentials, user, body.password):
            raise HTTPException(401, detail="Şifre yanlış. Bu davet için bu adresin hesabıyla giriş yapmalısınız.")
        await claim()
        # First organisation of this account: act in it. Otherwise the person keeps working where
        # they were; the invitation page then switches them if they wish.
        if not user.org_id:
            user.org_id = invite.org_id
            user.role = invite.role
    else:
        if not body.password:
            raise HTTPException(422, detail="Hesap oluşturmak için en az 8 karakterlik bir şifre gerekli.")
        await claim()
        user = User(
            email=normalize_email(invite.email),
            hashed_password=hash_password(body.password),
            full_name=body.full_name,
            role=invite.role,
            org_id=invite.org_id,
            email_verified_at=now,  # the invitation was e-mailed to this address
        )
        db.add(user)
        try:
            await db.flush()
        except IntegrityError:
            # Someone made an account for this address between the lookup and now.
            await db.rollback()
            raise HTTPException(409, detail="Bu adres için bir hesap az önce oluşturuldu; lütfen yeniden deneyin.") from None

    from app.services.org_membership import ensure_membership

    membership = await ensure_membership(
        db, user_id=str(user.id), org_id=str(invite.org_id), role=str(invite.role)
    )
    # Someone who was acting in another organisation before memberships existed must stay able to go back.
    if user.org_id and str(user.org_id) != str(invite.org_id):
        await ensure_membership(db, user_id=str(user.id), org_id=str(user.org_id), role=str(user.role))
    await record_decision(
        db, org_id=str(invite.org_id), kind=DecisionKind.MEMBER_CHANGE, target_type="org_membership",
        target_id=str(membership.id), outcome="joined", decided_via=DecidedVia.HUMAN, decided_by=str(user.id),
        evidence_refs=[{"type": "org_invite", "id": str(invite.id)}], after={"role": membership.role},
    )

    await db.commit()
    await db.refresh(user)

    access  = create_access_token(user.id, user.email, user.role, token_version=user.token_version)
    refresh = create_refresh_token(user.id, token_version=user.token_version)

    logger.info("Invite accepted: %s joined org %s", user.email, invite.org_id)

    return {
        "data": {
            "access_token":  access,
            "refresh_token": refresh,
            "token_type":    "bearer",
            "expires_in":    1800,
            "joined_org_id": str(invite.org_id),
            "user": {
                "user_id":  user.id,
                "email":    user.email,
                "role":     user.role,
                "org_id":   user.org_id,
            },
        },
        "error": None,
    }


def _proves_account(credentials: HTTPAuthorizationCredentials | None, user: User, password: str | None) -> bool:
    """The caller is this account: a valid access token of it, or its password."""
    from jose import JWTError

    from app.services.auth import decode_token, token_is_current, verify_password

    if credentials and credentials.credentials:
        try:
            payload = decode_token(credentials.credentials)
        except JWTError:
            payload = {}
        if (
            payload.get("type") == "access"
            and payload.get("sub") == str(user.id)
            and token_is_current(payload, user.token_version)
        ):
            return True
    return bool(password and user.hashed_password) and verify_password(password, user.hashed_password)


class SwitchOrgRequest(BaseModel):
    org_id: str


@router.get("/org/memberships")
async def list_memberships(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """The organisations the caller may act in, and the one they are acting in."""
    rows = (
        await db.execute(
            select(OrgMembership, Organization)
            .join(Organization, Organization.id == OrgMembership.org_id)
            .where(OrgMembership.user_id == str(current_user.id), Organization.is_active.is_(True))
            .order_by(Organization.name)
        )
    ).all()
    return {
        "data": {
            "active_org_id": current_user.org_id,
            "memberships": [
                {
                    "org_id": o.id,
                    "name": o.name,
                    "role": m.role,
                    "active": str(o.id) == str(current_user.org_id),
                }
                for m, o in rows
            ],
        },
        "error": None,
    }


@router.post("/org/switch")
async def switch_org(
    body: SwitchOrgRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Act in another organisation the caller is a member of.

    The only way `users.org_id` changes to an organisation the user did not
    create or accept an invitation to. A non-member gets the same 404 as for
    an organisation that does not exist: whether it exists is somebody else's
    fact. The role becomes the role of the membership, so an accountant is
    `smmm` in a client and keeps their own role at home.
    """
    from app.services.org_membership import ensure_membership

    user_row = await db.get(User, str(current_user.id))
    if user_row is None:  # pragma: no cover - the token resolved a moment ago
        raise HTTPException(status_code=401, detail="Kullanıcı bulunamadı.")

    target = (
        await db.execute(
            select(OrgMembership, Organization)
            .join(Organization, Organization.id == OrgMembership.org_id)
            .where(
                OrgMembership.user_id == str(user_row.id),
                OrgMembership.org_id == body.org_id,
                Organization.is_active.is_(True),
            )
        )
    ).first()
    if target is None:
        raise HTTPException(status_code=404, detail="Organizasyon bulunamadı.")
    membership, org = target

    # Leaving an organisation the user was in before memberships existed must
    # stay reversible: record it before switching away.
    if user_row.org_id and str(user_row.org_id) != str(org.id):
        await ensure_membership(
            db, user_id=str(user_row.id), org_id=str(user_row.org_id), role=str(user_row.role)
        )

    user_row.org_id = org.id
    user_row.role = membership.role
    await db.commit()
    logger.info("Org switch: user=%s -> org=%s role=%s", user_row.email, org.id, membership.role)
    return {"data": {"org_id": org.id, "name": org.name, "role": membership.role}, "error": None}


@router.get("/org/invites")
async def list_invites(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List pending invites for the org."""
    org = await _require_admin(current_user, db)
    result = await db.execute(
        select(OrgInvite)
        .where(OrgInvite.org_id == org.id, OrgInvite.accepted.is_(False))
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
    org = await _require_admin(current_user, db)
    result = await db.execute(
        select(OrgInvite).where(OrgInvite.id == invite_id, OrgInvite.org_id == org.id)
    )
    invite = result.scalar_one_or_none()
    if not invite:
        raise HTTPException(404, detail="Davet bulunamadı.")
    await record_decision(
        db, org_id=str(org.id), kind=DecisionKind.MEMBER_CHANGE, target_type="org_invite",
        target_id=str(invite.id), outcome="invite_cancelled", decided_via=DecidedVia.HUMAN,
        decided_by=str(current_user.id), before={"role": invite.role, "email": invite.email}, after=None,
    )
    await db.delete(invite)
    await db.commit()
    return {"data": {"cancelled": True}, "error": None}
