"""
FastAPI Auth Dependencies.

Usage in routers:
    @router.get("/my-endpoint")
    async def handler(
        current_user: CurrentUser,          # any authenticated user
        db: AsyncSession = Depends(get_db),
    ): ...

    @router.post("/admin-only")
    async def admin_handler(
        current_user: AdminUser,            # admin or owner only
    ): ...

    @router.delete("/owner-only")
    async def owner_handler(
        current_user: OwnerUser,
    ): ...
"""
from __future__ import annotations

from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User, role_gte
from app.services.auth_service import decode_token

_bearer = HTTPBearer(auto_error=False)

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated.",
    headers={"WWW-Authenticate": "Bearer"},
)

_FORBIDDEN = HTTPException(
    status_code=status.HTTP_403_FORBIDDEN,
    detail="Insufficient permissions.",
)


async def _resolve_user(
    credentials: HTTPAuthorizationCredentials | None,
    db: AsyncSession,
) -> User:
    """Extract and validate the JWT, then load the user from DB."""
    if not credentials:
        raise _UNAUTHORIZED

    try:
        payload = decode_token(credentials.credentials)
    except JWTError:
        raise _UNAUTHORIZED

    if payload.get("type") != "access":
        raise _UNAUTHORIZED

    user_id: str = payload.get("sub", "")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()

    if not user or not user.is_active:
        raise _UNAUTHORIZED

    return user


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: AsyncSession = Depends(get_db),
) -> User:
    return await _resolve_user(credentials, db)


# Typed aliases for role-gated endpoints
CurrentUser = Annotated[User, Depends(get_current_user)]


def _require_role(minimum_role: str):
    async def _checker(user: User = Depends(get_current_user)) -> User:
        if not role_gte(user.role, minimum_role):
            raise _FORBIDDEN
        return user
    return _checker


AnalystUser = Annotated[User, Depends(_require_role("analyst"))]
AdminUser = Annotated[User, Depends(_require_role("admin"))]
OwnerUser = Annotated[User, Depends(_require_role("owner"))]
