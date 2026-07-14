"""
Auth Service — password hashing and JWT token management.

Token strategy:
  - Access token:  short-lived (30 min), sent in Authorization header
  - Refresh token: long-lived (30 days), sent as httpOnly cookie
  - Both tokens include: user_id, org_id, role

Security:
  - Passwords hashed with bcrypt (passlib)
  - JWT signed with HS256 using BACKEND_SECRET_KEY
  - Token payload is minimal — no PII beyond user ID
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import get_settings

logger = logging.getLogger(__name__)

# bcrypt context — auto-upgrade hash strength on login if needed
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ACCESS_TOKEN_EXPIRE_MINUTES = 30
REFRESH_TOKEN_EXPIRE_DAYS = 30
ALGORITHM = "HS256"


# ---------------------------------------------------------------------------
# Password helpers
# ---------------------------------------------------------------------------

def hash_password(plain: str) -> str:
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_context.verify(plain, hashed)


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

def _make_token(
    data: dict[str, Any],
    expires_delta: timedelta,
) -> str:
    settings = get_settings()
    payload = {
        **data,
        "exp": datetime.now(timezone.utc) + expires_delta,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.backend_secret_key, algorithm=ALGORITHM)


def create_access_token(user_id: str, org_id: str, role: str) -> str:
    return _make_token(
        {"sub": user_id, "org": org_id, "role": role, "type": "access"},
        timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )


def create_refresh_token(user_id: str, org_id: str, role: str) -> str:
    return _make_token(
        {"sub": user_id, "org": org_id, "role": role, "type": "refresh"},
        timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
    )


def decode_token(token: str) -> dict[str, Any]:
    """
    Decode and verify a JWT. Raises JWTError on invalid/expired tokens.
    Returns the full payload dict.
    """
    settings = get_settings()
    return jwt.decode(token, settings.backend_secret_key, algorithms=[ALGORITHM])
