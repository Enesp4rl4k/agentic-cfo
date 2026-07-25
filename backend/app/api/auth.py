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
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Header, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User, UserRole
from app.services.auth import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_api_key,
)

router = APIRouter()
logger = logging.getLogger(__name__)
_bearer = HTTPBearer(auto_error=False)


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, description="Min 8 characters")
    full_name: str | None = None
    role: UserRole = UserRole.ANALYST


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

async def get_current_user(
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

        user = await db.get(User, user_id)
        if not user or not user.is_active:
            raise credentials_exception
        return user

    # ── Try API key ───────────────────────────────────────────────────────────
    if x_api_key:
        result = await db.execute(
            select(User).where(User.api_key == x_api_key, User.is_active == True)
        )
        user = result.scalar_one_or_none()
        if not user:
            raise credentials_exception
        return user

    raise credentials_exception


async def require_role(*roles: str):
    """
    Role-based access control dependency factory.

    Usage:
        @router.get("/admin-only")
        async def admin_endpoint(user = Depends(require_role("admin"))):
            ...
    """
    async def _check(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Bu işlem için '{'/'.join(roles)}' rolü gerekli.",
            )
        return user
    return _check


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/auth/register", status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Register a new user account."""
    # Check duplicate email
    result = await db.execute(select(User).where(User.email == body.email))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=400,
            detail="Bu e-posta adresi zaten kayıtlı.",
        )

    user = User(
        email=str(body.email),
        hashed_password=hash_password(body.password),
        full_name=body.full_name,
        role=body.role,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    logger.info("New user registered: %s (role=%s)", user.email, user.role)

    return {
        "data": {
            "user_id": user.id,
            "email":   user.email,
            "role":    user.role,
        },
        "error": None,
    }


@router.post("/auth/login")
async def login(
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Email/password login → returns access + refresh tokens."""
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(body.password, user.hashed_password):
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

    access_token  = create_access_token(user.id, user.email, user.role)
    refresh_token = create_refresh_token(user.id)

    # Update last login
    user.last_login_at = datetime.now(timezone.utc)
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
    if not user or not user.is_active:
        raise credentials_exception

    new_access = create_access_token(user.id, user.email, user.role)

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
    new_key = generate_api_key()
    current_user.api_key = new_key
    await db.commit()

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
    current_user.api_key = None
    await db.commit()
    return {"data": {"revoked": True}, "error": None}
