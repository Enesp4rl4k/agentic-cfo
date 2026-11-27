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
from datetime import timedelta
from typing import Any

import bcrypt
from jose import jwt

from app.config import get_settings
from app.core.clock import wall_now

# JWT constants
ACCESS_TOKEN_EXPIRE_MINUTES  = 30
REFRESH_TOKEN_EXPIRE_DAYS    = 7
ALGORITHM                    = "HS256"


# ── Password helpers ──────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    """Hash password using bcrypt (with 72-byte max length safety)."""
    pwd_bytes = password.encode("utf-8")[:72]
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pwd_bytes, salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Verify password with bcrypt."""
    try:
        return bcrypt.checkpw(plain.encode("utf-8")[:72], hashed.encode("utf-8"))
    except Exception:
        return False


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
    *,
    token_version: int = 0,
) -> str:
    # A token's times are checked against the wall clock (python-jose, the frontend's refresh rule), so they are
    # stamped by it, never by a pinned test clock (app/core/clock.py `wall_now`).
    issued = wall_now()
    expire = issued + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    payload: dict[str, Any] = {
        "sub":   user_id,
        "email": email,
        "role":  role,
        "type":  "access",
        "tv":    token_version,
        "exp":   expire,
        "iat":   issued,
        "jti":   str(uuid.uuid4()),
    }
    return jwt.encode(payload, _secret(), algorithm=ALGORITHM)


def create_refresh_token(user_id: str, *, token_version: int = 0) -> str:
    issued = wall_now()
    expire = issued + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    payload: dict[str, Any] = {
        "sub":  user_id,
        "type": "refresh",
        "tv":   token_version,
        "exp":  expire,
        "iat":  issued,
        "jti":  str(uuid.uuid4()),
    }
    return jwt.encode(payload, _secret(), algorithm=ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT token. Raises JWTError if invalid."""
    return jwt.decode(token, _secret(), algorithms=[ALGORITHM])


def token_is_current(payload: dict[str, Any], user_token_version: int) -> bool:
    """Whether a decoded token was issued under the user's current token version.

    A password reset raises `users.token_version`, which ends every session and refresh token
    issued before it. A token without the claim (issued before this existed) counts as version 0."""
    claimed = payload.get("tv", 0)
    return isinstance(claimed, int) and claimed == int(user_token_version or 0)


def generate_api_key() -> str:
    """Generate a cryptographically secure 32-byte hex API key."""
    return f"cfo_{secrets.token_hex(28)}"  # 'cfo_' prefix + 56 hex chars = 60 chars


def hash_api_key(key: str) -> str:
    """Hash an API key using SHA-256 for secure storage."""
    import hashlib
    return hashlib.sha256(key.encode("utf-8")).hexdigest()

