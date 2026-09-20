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
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
from jose import jwt

from app.config import get_settings

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
) -> str:
    expire = datetime.now(UTC) + (
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload: dict[str, Any] = {
        "sub":   user_id,
        "email": email,
        "role":  role,
        "type":  "access",
        "exp":   expire,
        "iat":   datetime.now(UTC),
        "jti":   str(uuid.uuid4()),
    }
    return jwt.encode(payload, _secret(), algorithm=ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    expire = datetime.now(UTC) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    payload: dict[str, Any] = {
        "sub":  user_id,
        "type": "refresh",
        "exp":  expire,
        "iat":  datetime.now(UTC),
        "jti":  str(uuid.uuid4()),
    }
    return jwt.encode(payload, _secret(), algorithm=ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT token. Raises JWTError if invalid."""
    return jwt.decode(token, _secret(), algorithms=[ALGORITHM])


def generate_api_key() -> str:
    """Generate a cryptographically secure 32-byte hex API key."""
    return f"cfo_{secrets.token_hex(28)}"  # 'cfo_' prefix + 56 hex chars = 60 chars


def hash_api_key(key: str) -> str:
    """Hash an API key using SHA-256 for secure storage."""
    import hashlib
    return hashlib.sha256(key.encode("utf-8")).hexdigest()

