"""
Auth Service — JWT token management and password hashing.

Uses:
  - passlib[bcrypt] for password hashing (already in requirements.txt)
  - python-jose[cryptography] for JWT (already in requirements.txt)

Token lifecycle:
  - Access token:  30 minutes (short-lived, used for API calls)
  - Refresh token: 7 days (long-lived, stored client-side)
"""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import get_settings

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# JWT constants
ACCESS_TOKEN_EXPIRE_MINUTES  = 30
REFRESH_TOKEN_EXPIRE_DAYS    = 7
ALGORITHM                    = "HS256"


# ── Password helpers ──────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_context.verify(plain, hashed)


# ── JWT helpers ───────────────────────────────────────────────────────────────

def _secret() -> str:
    settings = get_settings()
    # Use SECRET_KEY from settings if available, fall back to a fixed default for dev
    return getattr(settings, "secret_key", "dev-secret-change-in-production-32chars!!")


def create_access_token(
    user_id: str,
    email: str,
    role: str,
    expires_delta: timedelta | None = None,
) -> str:
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload: dict[str, Any] = {
        "sub":   user_id,
        "email": email,
        "role":  role,
        "type":  "access",
        "exp":   expire,
        "iat":   datetime.now(timezone.utc),
        "jti":   str(uuid.uuid4()),
    }
    return jwt.encode(payload, _secret(), algorithm=ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    payload: dict[str, Any] = {
        "sub":  user_id,
        "type": "refresh",
        "exp":  expire,
        "iat":  datetime.now(timezone.utc),
        "jti":  str(uuid.uuid4()),
    }
    return jwt.encode(payload, _secret(), algorithm=ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT token. Raises JWTError if invalid."""
    return jwt.decode(token, _secret(), algorithms=[ALGORITHM])


def generate_api_key() -> str:
    """Generate a cryptographically secure 32-byte hex API key."""
    return secrets.token_hex(32)  # 64 chars hex
