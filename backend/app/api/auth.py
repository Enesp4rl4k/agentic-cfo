"""
Auth API — Registration, login, token refresh, and profile endpoints.

POST /api/v1/auth/register    — create a new user account
POST /api/v1/auth/login       — email/password → access + refresh tokens
POST /api/v1/auth/refresh     — refresh token → new access token
GET  /api/v1/auth/me          — current user profile (requires auth)
POST /api/v1/auth/api-key     — generate/rotate API key
DELETE /api/v1/auth/api-key   — revoke API key

Auth header format:
  Authorization: Bearer <access_token>
  OR
  X-API-Key: <api_key>
"""
from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.email_address import normalize_email
from app.database import get_db
from app.models.user import User, UserRole
from app.services import email_verification, mail_capability, outbox, pilot_invites, registration
from app.services.auth import (
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_api_key,
    hash_api_key,
    hash_password,
    token_is_current,
    verify_password,
)

router = APIRouter()
logger = logging.getLogger(__name__)
_bearer = HTTPBearer(auto_error=False)

# ── PERF-2: Short-lived in-process user cache ─────────────────────────────────
# Avoids a DB round-trip on every authenticated request for the same user.
# TTL is intentionally short (matches access token window) so revocations
# and role changes propagate within 60 seconds.
#
# ⚠️  MULTI-PROCESS WARNING: This cache is per-process (not shared across
# gunicorn/uvicorn workers). In a multi-worker deployment:
#   - Role changes / revocations may not propagate to all workers for up to TTL seconds
#   - Each worker maintains its own independent copy
#   - For production multi-worker deployments, replace with Redis:
#       await redis.setex(f"user:{user_id}", 60, user.model_dump_json())
#   - Single-process deployments (default Docker setup) are unaffected.
#
# Note: lru_cache on an async function caches the coroutine object, not the
# result. We use a plain dict + timestamp instead.


# PERF-2: one PK lookup per request adds up, so the resolved user is cached for
# a minute. The catch is what gets cached.
#
# There is no per-process user cache. One used to hold the user for 60 s, and
# with two workers a removal, role change, deactivation or organisation switch
# reached the other worker up to a minute late, while `acting_role` fell back
# to the cached `users.role`. The facts that decide access (is_active, org_id,
# role, membership) are read on every request: one primary-key select.


# ── Pydantic schemas ──────────────────────────────────────────────────────────

UNVERIFIED_MESSAGE = (
    "E-posta adresiniz henüz doğrulanmadı. Size gönderilen doğrulama bağlantısını açın "
    "ya da yeni bir bağlantı isteyin."
)


class RegisterRequest(BaseModel):
    # No `role` field. It used to be here with an ANALYST default, which meant
    # anyone could POST `{"role": "owner"}` and self-register as an owner —
    # privilege escalation through an ordinary public endpoint. Role is assigned
    # by the server: everyone starts as an analyst, and creating a workspace
    # promotes the creator to owner (see POST /org/create).
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=8, description="Min 8 characters")
    full_name: str | None = None
    # The secret of a pilot invitation (services/pilot_invites.py). With it, and only with it, an account and
    # its company are created when REGISTRATION_MODE is not `open`.
    invite_token: str | None = Field(default=None, min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token:  str
    refresh_token: str
    token_type:    str = "bearer"
    expires_in:    int = 1800  # 30 minutes


class RefreshRequest(BaseModel):
    refresh_token: str


# ── Dependency: get current user ──────────────────────────────────────────────

def _refuse_outside_allow_list(request: Request, user: User, enabled: bool | None, stored: str | None) -> None:
    """The organisation the user acts in may limit the addresses it can be acted in from.

    `enabled` / `stored` ride on the query that loaded the user (an outer join to the organisation):
    no extra round trip per request."""
    from app.core.client_ip import client_ip
    from app.services import ip_allowlist

    if not user.org_id or not enabled or ip_allowlist.exempt(request.url.path):
        return
    refusal = ip_allowlist.refusal_for(stored, client_ip(request))
    if refusal:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=refusal)


def _user_with_allow_list(*where: Any):
    """User columns plus the acting organisation's allow-list fields, in one statement."""
    from app.models.organization import Organization

    return (
        select(User, Organization.ip_whitelist_enabled, Organization.ip_whitelist)
        .outerjoin(Organization, Organization.id == User.org_id)
        .where(*where)
    )


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    x_api_key: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    FastAPI dependency — resolves to the authenticated User.

    Supports two auth methods (checked in order):
    1. Bearer JWT token (Authorization: Bearer <token>)
    2. API key header (X-API-Key: <key>)

    Raises HTTP 401 if neither is valid.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Kimlik doğrulaması başarısız. Lütfen giriş yapın.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    unverified_exception = HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail=UNVERIFIED_MESSAGE,
    )

    # ── Try JWT token ─────────────────────────────────────────────────────────
    if credentials and credentials.credentials:
        try:
            payload = decode_token(credentials.credentials)
            if payload.get("type") != "access":
                raise credentials_exception
            user_id: str = payload.get("sub", "")
            if not user_id:
                raise credentials_exception
        except JWTError:
            raise credentials_exception

        found = (await db.execute(_user_with_allow_list(User.id == user_id))).first()
        user = found[0] if found else None
        if not user or not user.is_active or not token_is_current(payload, user.token_version):
            raise credentials_exception
        if not email_verification.is_verified(user):
            raise unverified_exception
        _refuse_outside_allow_list(request, user, found[1], found[2])

        # Detached, so every caller gets the same kind of object (reads work; endpoints
        # that change the user re-load it through their own session, see `create_org`).
        db.expunge(user)
        return user

    # ── Try API key ───────────────────────────────────────────────────────────
    if x_api_key:
        hashed_key = hash_api_key(x_api_key)
        result = await db.execute(
            _user_with_allow_list((User.api_key == hashed_key) | (User.api_key == x_api_key), User.is_active)
        )
        found = result.first()
        user = found[0] if found else None
        if not user:
            raise credentials_exception
        if not email_verification.is_verified(user):
            raise unverified_exception
        _refuse_outside_allow_list(request, user, found[1], found[2])
        return user

    raise credentials_exception


def require_role(*roles: str):
    """
    Role-based access control dependency factory.

    Returns a FastAPI dependency (synchronous callable returning a coroutine),
    so FastAPI can inject it correctly via Depends().

    Usage:
        @router.get("/admin-only")
        async def admin_endpoint(user: User = Depends(require_role("admin", "owner"))):
            ...

    Note: `async def require_role` was a bug — it returned a coroutine instead
    of a dependency callable. Fixed to a plain `def` factory.
    """
    async def _check(
        user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
    ) -> User:
        from app.services.acting_role import acting_role

        role = await acting_role(db, user)
        if role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Bu işlem için '{'/'.join(roles)}' rolü gerekli. "
                       f"Mevcut rol: '{role}'.",
            )
        return user
    return _check


# ── Endpoints ─────────────────────────────────────────────────────────────────

# Compared against when the account does not exist or has no password, so an unknown address costs
# the same bcrypt work as a wrong password (login timing does not reveal which addresses exist).
_DUMMY_HASH = hash_password("not-a-real-password")


def _accepted() -> dict[str, Any]:
    """The one answer of /auth/register under verification (identical for new and existing addresses).

    `mail_delivery` / `mail_notice` are facts about the deployment (is a mail sender configured), the same
    for every address, so "check your e-mail" is never said when nothing can be sent."""
    return {
        "data": {"accepted": True, "verification_required": True, **mail_capability.fields()},
        "error": None,
    }


def _closed_answer() -> JSONResponse:
    """Sign-up without an invitation while REGISTRATION_MODE is not `open`: nothing is created.

    Independent of the address (it says nothing about which accounts exist), so it needs no disguise."""
    return JSONResponse(
        status_code=status.HTTP_403_FORBIDDEN,
        content={
            "data": {"state": "invite_only", **registration.public_view()},
            "error": registration.refusal_message(),
        },
    )


@router.get("/auth/registration")
async def registration_policy() -> dict[str, Any]:
    """Who may sign up, for the register page to say so before the form (no account data)."""
    return {"data": registration.public_view(), "error": None}


async def _register_with_pilot_invite(body: RegisterRequest, db: AsyncSession) -> dict[str, Any] | JSONResponse:
    """The invited owner of a new company signs up: account + company in one step, signed in at once."""
    from app.api.password_reset import hold_to_floor

    started = time.monotonic()
    password_hash = hash_password(body.password)
    try:
        user, org = await pilot_invites.redeem(
            db, str(body.invite_token), email=str(body.email), hashed_password=password_hash,
            full_name=body.full_name,
        )
        await db.commit()
    except pilot_invites.PilotInviteError as err:
        await db.rollback()
        await hold_to_floor(started)
        return JSONResponse(status_code=err.status_code, content={"data": None, "error": err.detail, "detail": err.detail})
    await db.refresh(user)
    logger.info("Pilot invite redeemed: user %s owns organisation %s", user.id, org.id)
    return {
        "data": {
            "user_id": user.id, "email": user.email, "role": user.role, "org_id": str(org.id),
            "org_name": org.name, "verification_required": False, "pilot_invite": True,
            "access_token": create_access_token(user.id, user.email, user.role, token_version=user.token_version),
            "refresh_token": create_refresh_token(user.id, token_version=user.token_version),
            "token_type": "bearer", "expires_in": 1800,
        },
        "error": None,
    }


async def _mail_existing_account(db: AsyncSession, user: User) -> None:
    """Tell the holder of an existing address that someone tried to register it (once per cool-down).

    Never a verification link: for an unverified account that would hand the account to whoever
    registered first. The reset page proves the mailbox and sets the password itself."""
    from app.config import get_settings
    from app.services import outbox_immediate

    settings = get_settings()
    if not user.is_active or await outbox_immediate.mailed_recently(
        db, kind="account_exists", email=user.email, minutes=settings.auth_mail_cooldown_minutes
    ):
        return
    base = settings.frontend_url.rstrip("/")
    await outbox_immediate.enqueue_account_exists(
        db, user_id=user.id, org_id=str(user.org_id) if user.org_id else None, email=user.email,
        login_url=f"{base}/auth/login", reset_url=f"{base}/auth/forgot-password",
    )
    await db.commit()
    outbox.kick()


@router.post("/auth/register", status_code=status.HTTP_201_CREATED, response_model=None)
async def register(
    body: RegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any] | JSONResponse:
    """Register a new user account.

    REGISTRATION_MODE decides who may. `open`: anyone, as below. `invite_only` / `closed`: only a request
    carrying a valid pilot-invite token creates anything (an account that owns a new company); every other
    request is refused with 403 and creates nothing, for any address alike.

    With e-mail verification required (the default) the answer is the same for a new and an
    existing address: status, body and minimum duration. A new address gets the verification link;
    an existing one gets a "you already have an account" mail (sign-in and reset links, no token)
    and nothing changes. So the page cannot be used to ask which addresses exist. Without
    verification (an explicit opt-out for deployments with no mail) there is no private channel to
    tell the person, so the old explicit error stays."""
    from app.api.password_reset import hold_to_floor

    if not registration.is_open():
        if not body.invite_token:
            return _closed_answer()
        return await _register_with_pilot_invite(body, db)
    started = time.monotonic()
    verification = email_verification.required()
    address = normalize_email(str(body.email))
    password_hash = hash_password(body.password)  # the same work whether or not the address exists
    existing = (await db.execute(select(User).where(User.email == normalize_email(address)))).scalar_one_or_none()
    if existing is not None:
        if not verification:
            raise HTTPException(status_code=400, detail="Bu e-posta adresi zaten kayıtlı.")
        await _mail_existing_account(db, existing)
        await hold_to_floor(started)
        return _accepted()

    user = User(
        email=address,
        hashed_password=password_hash,
        full_name=body.full_name,
        role=UserRole.ANALYST,
    )
    db.add(user)
    try:
        await db.flush()
        if verification:
            # The link goes out through the outbox; the account cannot sign in until it is opened.
            await email_verification.issue(db, user)
        await db.commit()
    except IntegrityError:
        # Two sign-ups for one address at once: the loser gets the ordinary answer.
        await db.rollback()
        if not verification:
            raise HTTPException(status_code=400, detail="Bu e-posta adresi zaten kayıtlı.") from None
        await hold_to_floor(started)
        return _accepted()
    await db.refresh(user)
    if verification:
        outbox.kick()

    logger.info("New user registered: %s (role=%s)", user.id, user.role)
    if verification:
        await hold_to_floor(started)
        return _accepted()

    return {
        "data": {
            "user_id": user.id,
            "email":   user.email,
            "role":    user.role,
            "verification_required": verification,
        },
        "error": None,
    }


@router.post("/auth/login", response_model=None)
async def login(
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any] | JSONResponse:
    """Email/password login → returns access + refresh tokens."""
    result = await db.execute(select(User).where(User.email == normalize_email(str(body.email))))
    user = result.scalar_one_or_none()

    stored = (user.hashed_password if user else None) or _DUMMY_HASH
    password_ok = verify_password(body.password, stored)  # always runs: an unknown address costs the same
    if not user or not user.hashed_password or not password_ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="E-posta veya şifre hatalı.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Hesabınız devre dışı bırakılmış.",
        )

    if not email_verification.is_verified(user):
        # Only after the right password, so this says nothing to someone who does not hold the account.
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"data": {"state": "email_unverified"}, "error": UNVERIFIED_MESSAGE},
        )

    access_token  = create_access_token(user.id, user.email, user.role, token_version=user.token_version)
    refresh_token = create_refresh_token(user.id, token_version=user.token_version)

    # Update last login
    user.last_login_at = datetime.now(UTC)
    await db.commit()

    logger.info("User logged in: %s", user.email)

    return {
        "data": {
            "access_token":  access_token,
            "refresh_token": refresh_token,
            "token_type":    "bearer",
            "expires_in":    1800,
            "user": {
                "user_id":   user.id,
                "email":     user.email,
                "full_name": user.full_name,
                "role":      user.role,
                # NextAuth bakes this into the session at sign-in; the CEO
                # synthesize button and org-scoped queries gate on it.
                "org_id":    user.org_id,
            },
        },
        "error": None,
    }


@router.post("/auth/refresh")
async def refresh_token(
    body: RefreshRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Exchange a refresh token for a new access token."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Geçersiz refresh token.",
    )
    try:
        payload = decode_token(body.refresh_token)
        if payload.get("type") != "refresh":
            raise credentials_exception
        user_id = payload.get("sub", "")
    except JWTError:
        raise credentials_exception

    user = await db.get(User, user_id)
    if (
        not user or not user.is_active or not token_is_current(payload, user.token_version)
        or not email_verification.is_verified(user)
    ):
        raise credentials_exception

    new_access = create_access_token(user.id, user.email, user.role, token_version=user.token_version)

    return {
        "data": {
            "access_token": new_access,
            "token_type":   "bearer",
            "expires_in":   1800,
        },
        "error": None,
    }


@router.get("/auth/me")
async def get_me(current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    """Get the authenticated user's profile."""
    return {
        "data": {
            "user_id":       current_user.id,
            "email":         current_user.email,
            "full_name":     current_user.full_name,
            "role":          current_user.role,
            "org_id":        current_user.org_id,
            "is_active":     current_user.is_active,
            "has_api_key":   current_user.api_key is not None,
            "last_login_at": current_user.last_login_at.isoformat() if current_user.last_login_at else None,
            "created_at":    current_user.created_at.isoformat(),
        },
        "error": None,
    }


@router.post("/auth/api-key")
async def create_api_key(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Generate or rotate API key for programmatic access.

    The key is returned once — store it securely. It cannot be retrieved again.
    To get a new key, call this endpoint again (old key is revoked).
    """
    # `current_user` is detached (see the cache note above), so the row has to be
    # re-loaded through this request's session before it can be written to.
    # Assigning to the detached instance committed nothing: the key came back to
    # the caller while the database still held the old one, so every request
    # made with the new key answered 401.
    user_row = await db.get(User, str(current_user.id))
    if user_row is None:  # pragma: no cover - the token resolved a moment ago
        raise HTTPException(status_code=401, detail="Kullanıcı bulunamadı.")

    new_key = generate_api_key()
    user_row.api_key = hash_api_key(new_key)
    await db.commit()

    # Invalidate cache so next request reloads the updated user from DB
    logger.info("API key rotated for user: %s", current_user.email)

    return {
        "data": {
            "api_key":  new_key,
            "note":     "Bu anahtarı güvenli bir yerde saklayın. Tekrar gösterilmeyecek.",
            "usage":    "X-API-Key: <api_key> başlığı ile kullanın.",
        },
        "error": None,
    }


@router.delete("/auth/api-key")
async def revoke_api_key(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Revoke the current API key."""
    user_row = await db.get(User, str(current_user.id))
    if user_row is None:  # pragma: no cover - the token resolved a moment ago
        raise HTTPException(status_code=401, detail="Kullanıcı bulunamadı.")
    user_row.api_key = None
    await db.commit()
    return {"data": {"revoked": True}, "error": None}
