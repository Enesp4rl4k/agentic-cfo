"""
Cryptographic utilities for sensitive financial data encryption at rest (AES-256-GCM).

Provides:
  - encrypt_field: Encrypts arbitrary plaintext string using AES-256-GCM
  - decrypt_field: Decrypts ciphertext (backward compatible with unencrypted plaintext)
  - EncryptedString: SQLAlchemy TypeDecorator for transparent field-level encryption
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import String, TypeDecorator

logger = logging.getLogger(__name__)

PREFIX_V1 = "enc:v1:"


def _get_key(key: bytes | str | None = None) -> bytes:
    """Derive 32-byte AES-256 key from config or provided argument."""
    if key is not None:
        if isinstance(key, str):
            return hashlib.sha256(key.encode("utf-8")).digest()
        if len(key) == 32:
            return key
        return hashlib.sha256(key).digest()

    from app.config import get_settings

    settings = get_settings()
    configured_key: str = (
        getattr(settings, "encryption_key", None)
        or getattr(settings, "backend_secret_key", None)
        or "default-insecure-dev-key-change-in-prod"
    )
    return hashlib.sha256(configured_key.encode("utf-8")).digest()


def encrypt_field(plaintext: str | None, key: bytes | str | None = None) -> str | None:
    """
    Encrypt plaintext string using AES-256-GCM.
    Returns: 'enc:v1:<base64(nonce_12B + ciphertext_and_tag)>' or None if input is None.
    """
    if plaintext is None:
        return None
    if not isinstance(plaintext, str):
        plaintext = str(plaintext)

    # If already encrypted, do not double-encrypt
    if plaintext.startswith(PREFIX_V1):
        return plaintext

    raw_key = _get_key(key)
    aesgcm = AESGCM(raw_key)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    payload = nonce + ciphertext
    encoded = base64.urlsafe_b64encode(payload).decode("ascii")
    return f"{PREFIX_V1}{encoded}"


def decrypt_field(ciphertext: str | None, key: bytes | str | None = None) -> str | None:
    """
    Decrypt ciphertext produced by encrypt_field.
    Gracefully returns original value if string is unencrypted plaintext (backward compatibility).
    """
    if ciphertext is None:
        return None
    if not isinstance(ciphertext, str):
        return str(ciphertext)

    if not ciphertext.startswith(PREFIX_V1):
        return ciphertext

    try:
        raw_key = _get_key(key)
        aesgcm = AESGCM(raw_key)
        encoded = ciphertext[len(PREFIX_V1) :]
        payload = base64.urlsafe_b64decode(encoded.encode("ascii"))
        if len(payload) < 28:  # 12 byte nonce + 16 byte min tag
            logger.warning("Malformed encrypted payload; length=%d", len(payload))
            return ciphertext
        nonce = payload[:12]
        ct = payload[12:]
        decrypted_bytes = aesgcm.decrypt(nonce, ct, None)
        return decrypted_bytes.decode("utf-8")
    except Exception as exc:
        logger.error("Failed to decrypt field: %s", exc)
        return ciphertext


class EncryptedString(TypeDecorator[str]):
    """
    SQLAlchemy column type for field-level AES-256-GCM encryption.
    Stores data encrypted in the database, transparently decrypts in Python.
    """

    impl = String
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        return encrypt_field(str(value))

    def process_result_value(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        return decrypt_field(str(value))
