"""
Auth API — register, login, refresh, me, logout.

Endpoints:
  POST /api/v1/auth/register   — Create org + owner user
  POST /api/v1/auth/login      — Get access + refresh tokens
  POST /api/v1/auth/refresh    — Rotate tokens using refresh cookie
  GET  /api/v1/auth/me         — Get current user profile
  POST /api/v1/auth/logout     — Clear refresh cookie
  POST /api/v1/auth/invite     — Admin invites a user to their org (stub)

Token flow:
  - Access token: returned in JSON body (stored in memory by frontend)
  - Refresh token: set as httpOnly, Secure, SameSite=Lax cookie
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.organization import Organization
from app.models.user import User, UserRole
from app.services.auth_service import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
    REFRESH_TOKEN_EXPIRE_DAYS,
)
from app.api.deps import CurrentUser

router = APIRouter(prefix="/auth", tags=["auth"])

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{1,48}[a-z0-9]$")


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class RegisterRequest(BaseModel):
    org_name: str
    org_slug: str
    full_name: str
    email: EmailStr
    password: str

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters.")
        return v

    @field_validator("org_slug")
    @classmethod
    def slug_format(cls, v: str) -> str:
        if not _SLUG_RE.match(v):
            raise ValueError(
                "Slug must be 3–50 characters, lowercase letters, digits, and hyphens only."
            )
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class InviteRequest(BaseModel):
    email: EmailStr
    full_name: str
    role: str = UserRole.ANALYST

    @field_validator("role")
    @classmethod
    def valid_role(cls, v: str) -> str:
        allowed = {UserRole.ANALYST, UserRole.ADMIN, UserRole.VIEWER}
        if v not in allowed:
            raise ValueError(f"Role must be one of: {allowed}")
        return v


# ---------------------------------------------------------------------------
# Cookie helper
# ---------------------------------------------------------------------------

def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key="refresh_token",
        value=token,
        httponly=True,
        secure=False,   # set True in production behind HTTPS
        samesite="lax",
        max_age=REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        path="/api/v1/auth/refresh",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(key="refresh_token", path="/api/v1/auth/refresh")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Create a new organization and its first owner user.
    Returns access token in body + refresh token as httpOnly cookie.
    """
    # Check slug uniqueness
    existing_org = await db.execute(
        select(Organization).where(Organization.slug == body.org_slug)
    )
    if existing_org.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Organization slug already taken.",
        )

    # Check email uniqueness
    existing_user = await db.execute(
        select(User).where(User.email == body.email)
    )
    if existing_user.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered.",
        )

    # Create org
    org = Organization(
        id=str(uuid.uuid4()),
        name=body.org_name,
        slug=body.org_slug,
        plan="free",
    )
    db.add(org)
    await db.flush()  # get org.id before creating user

    # Create owner user
    user = User(
        id=str(uuid.uuid4()),
        organization_id=org.id,
        email=body.email,
        hashed_password=hash_password(body.password),
        full_name=body.full_name,
        role=UserRole.OWNER,
        is_active=True,
        is_verified=True,  # auto-verify on registration (add email flow later)
    )
    db.add(user)
    await db.commit()

    access = create_access_token(user.id, org.id, user.role)
    refresh = create_refresh_token(user.id, org.id, user.role)
    _set_refresh_cookie(response, refresh)

    return {
        "data": {
            "access_token": access,
            "token_type": "bearer",
            "user": {
                "id": user.id,
                "email": user.email,
                "full_name": user.full_name,
                "role": user.role,
                "organization": {"id": org.id, "name": org.name, "slug": org.slug, "plan": org.plan},
            },
        },
        "error": None,
    }


@router.post("/login")
async def login(
    body: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Authenticate and return tokens."""
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalars().first()

    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated.",
        )

    # Update last login
    user.last_login_at = datetime.now(timezone.utc)
    await db.commit()

    # Load org
    org = await db.get(Organization, user.organization_id)

    access = create_access_token(user.id, user.organization_id, user.role)
    refresh = create_refresh_token(user.id, user.organization_id, user.role)
    _set_refresh_cookie(response, refresh)

    return {
        "data": {
            "access_token": access,
            "token_type": "bearer",
            "user": {
                "id": user.id,
                "email": user.email,
                "full_name": user.full_name,
                "role": user.role,
                "organization": {
                    "id": org.id if org else None,
                    "name": org.name if org else None,
                    "slug": org.slug if org else None,
                    "plan": org.plan if org else None,
                },
            },
        },
        "error": None,
    }


@router.post("/refresh")
async def refresh_tokens(
    response: Response,
    db: AsyncSession = Depends(get_db),
    refresh_token: str | None = Cookie(default=None),
) -> dict:
    """Rotate access + refresh tokens using the httpOnly cookie."""
    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No refresh token.")

    from jose import JWTError
    try:
        payload = decode_token(refresh_token)
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token.")

    if payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Wrong token type.")

    user = await db.get(User, payload.get("sub", ""))
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found.")

    access = create_access_token(user.id, user.organization_id, user.role)
    new_refresh = create_refresh_token(user.id, user.organization_id, user.role)
    _set_refresh_cookie(response, new_refresh)

    return {"data": {"access_token": access, "token_type": "bearer"}, "error": None}


@router.get("/me")
async def get_me(current_user: CurrentUser, db: AsyncSession = Depends(get_db)) -> dict:
    """Return current user profile and organization."""
    org = await db.get(Organization, current_user.organization_id)
    return {
        "data": {
            "id": current_user.id,
            "email": current_user.email,
            "full_name": current_user.full_name,
            "role": current_user.role,
            "is_active": current_user.is_active,
            "created_at": current_user.created_at.isoformat(),
            "last_login_at": current_user.last_login_at.isoformat() if current_user.last_login_at else None,
            "organization": {
                "id": org.id if org else None,
                "name": org.name if org else None,
                "slug": org.slug if org else None,
                "plan": org.plan if org else None,
            },
        },
        "error": None,
    }


@router.post("/logout")
async def logout(response: Response) -> dict:
    """Clear the refresh token cookie."""
    _clear_refresh_cookie(response)
    return {"data": {"logged_out": True}, "error": None}


@router.post("/invite", status_code=status.HTTP_201_CREATED)
async def invite_user(
    body: InviteRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Admin invites a new user to their organization."""
    from app.models.user import role_gte
    if not role_gte(current_user.role, "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required.")

    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalars().first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered.")

    # Create user with a temporary password — they should reset via email (TODO: email flow)
    temp_password = str(uuid.uuid4())[:12]
    user = User(
        id=str(uuid.uuid4()),
        organization_id=current_user.organization_id,
        email=body.email,
        hashed_password=hash_password(temp_password),
        full_name=body.full_name,
        role=body.role,
        is_active=True,
        is_verified=False,
    )
    db.add(user)
    await db.commit()

    return {
        "data": {
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role,
            "temp_password": temp_password,  # TODO: send via email instead
        },
        "error": None,
    }
