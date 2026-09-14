"""Symmetric encryption for connector secrets (PATs, refresh tokens).

Uses `settings.field_encryption_key` (a real Fernet key) when configured. In dev,
falls back to a Fernet key *derived* from `backend_secret_key` — reversible and
consistent, never plaintext. Production must set `FIELD_ENCRYPTION_KEY`.

A proper OAuth broker with rotation is Faz 17 / a DISPATCH item; this module is
the interim, and deliberately narrow: encrypt/decrypt a short string.
"""
from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken


def _fernet() -> Fernet:
    from app.config import get_settings

    settings = get_settings()
    key = (settings.field_encryption_key or "").strip()
    if key:
        return Fernet(key.encode())
    # Dev fallback: derive a stable Fernet key from the backend secret.
    digest = hashlib.sha256(settings.backend_secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:  # wrong key / corrupted blob
        raise ValueError("connector secret could not be decrypted") from exc
