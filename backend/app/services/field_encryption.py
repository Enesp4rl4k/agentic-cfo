"""
Field-Level Encryption Service — SEC-2

AES-256-GCM ile hassas finansal veri şifreleme.

Neden field-level (tam disk şifreleme değil)?
  - Veritabanı yöneticisi bile şifreli veri göremez
  - Farklı org'lar farklı anahtarlarla şifrelenebilir (key isolation)
  - Key rotation: eski veriler yeniden şifrelenebilir (geçmiş uyumlu)
  - KVKK/GDPR: "unutulma hakkı" = anahtarı sil → veri erişilemez

Şifrelenen alanlar:
  - Transaction.description (kişisel veri içerebilir)
  - Transaction.vendor (iş ilişkisi bilgisi)
  - AnalysisJob.result (tüm finansal analiz sonucu)
  - CompanyContext (org-level state)

Format: base64(iv || ciphertext || tag)
  - iv:         12 byte (random, her şifrelemede farklı)
  - ciphertext: değişken uzunluk (plaintext ile aynı)
  - tag:        16 byte (authenticity check)

Key management:
  - Master key: .env'den FIELD_ENCRYPTION_KEY (32 byte, base64)
  - Key ID: rotasyon için — her org hangi key versiyonuyla şifrelendiğini bilir
  - Fallback: key yoksa plaintext döner (backward compat)

DDIA prensip: "Şifreleme = veri dönüşümü." Saf fonksiyon, yan etki yok.
"""
from __future__ import annotations

import base64
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# Current key version — increment on rotation
CURRENT_KEY_VERSION = "v1"


class FieldEncryption:
    """
    AES-256-GCM field-level encryption.

    Usage:
        enc = FieldEncryption(key_bytes)
        token = enc.encrypt("sensitive data")
        plain = enc.decrypt(token)
    """

    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("Encryption key must be exactly 32 bytes (256 bits)")
        self._key = key

    def encrypt(self, plaintext: str | None) -> str | None:
        """
        Encrypt plaintext string → base64 token.
        Returns None if plaintext is None.
        Returns plaintext unchanged if encryption is unavailable.
        """
        if plaintext is None:
            return None
        if not plaintext:
            return plaintext

        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            aesgcm = AESGCM(self._key)
            iv      = os.urandom(12)
            ct      = aesgcm.encrypt(iv, plaintext.encode("utf-8"), None)
            # Format: base64(iv + ciphertext_with_tag)
            raw     = iv + ct
            return "enc:" + base64.b64encode(raw).decode("ascii")
        except ImportError:
            logger.debug("cryptography package not installed — field encryption disabled")
            return plaintext
        except Exception as exc:
            logger.error("Field encryption failed: %s", exc)
            return plaintext

    def decrypt(self, token: str | None) -> str | None:
        """
        Decrypt an encrypted token → plaintext string.
        Passthrough for unencrypted values (backward compat).
        """
        if token is None:
            return None
        if not token:
            return token
        if not token.startswith("enc:"):
            return token  # Not encrypted — return as-is

        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            raw    = base64.b64decode(token[4:])
            iv     = raw[:12]
            ct     = raw[12:]
            aesgcm = AESGCM(self._key)
            plain  = aesgcm.decrypt(iv, ct, None)
            return plain.decode("utf-8")
        except ImportError:
            logger.debug("cryptography package not installed — returning raw token")
            return token
        except Exception as exc:
            logger.error("Field decryption failed (possible key mismatch): %s", exc)
            return token  # Return ciphertext rather than crash

    def encrypt_dict(self, data: dict, fields: list[str]) -> dict:
        """Encrypt specific fields in a dict. Returns a new dict."""
        result = dict(data)
        for field in fields:
            if field in result and isinstance(result[field], str):
                result[field] = self.encrypt(result[field])
        return result

    def decrypt_dict(self, data: dict, fields: list[str]) -> dict:
        """Decrypt specific fields in a dict. Returns a new dict."""
        result = dict(data)
        for field in fields:
            if field in result and isinstance(result[field], str):
                result[field] = self.decrypt(result[field])
        return result

    @staticmethod
    def is_encrypted(value: str | None) -> bool:
        """Check if a value is encrypted."""
        return bool(value and value.startswith("enc:"))


# ── Key management ────────────────────────────────────────────────────────────

class KeyManager:
    """
    Manages encryption keys with rotation support.

    Keys are identified by version (v1, v2, …).
    When rotating, the new key is used for writes, all old keys are kept for reads.
    """

    def __init__(self) -> None:
        self._keys: dict[str, bytes] = {}
        self._current: str = CURRENT_KEY_VERSION
        self._loaded    = False

    def _load(self) -> None:
        if self._loaded:
            return
        from app.config import get_settings
        settings = get_settings()

        raw_key = getattr(settings, "field_encryption_key", "")
        if raw_key:
            try:
                key_bytes = base64.b64decode(raw_key)
                if len(key_bytes) == 32:
                    self._keys[CURRENT_KEY_VERSION] = key_bytes
                else:
                    logger.warning(
                        "FIELD_ENCRYPTION_KEY must be 32 bytes (base64). "
                        "Got %d bytes — field encryption disabled.", len(key_bytes)
                    )
            except Exception as exc:
                logger.warning("Failed to load FIELD_ENCRYPTION_KEY: %s", exc)
        self._loaded = True

    def is_enabled(self) -> bool:
        """Return True if a valid encryption key is configured."""
        self._load()
        return bool(self._keys)

    def current_encryptor(self) -> FieldEncryption | None:
        """Return an encryptor using the current key, or None if disabled."""
        self._load()
        key = self._keys.get(self._current)
        return FieldEncryption(key) if key else None

    def get_encryptor(self, version: str) -> FieldEncryption | None:
        """Get encryptor for a specific key version (for rotation/decryption)."""
        self._load()
        key = self._keys.get(version)
        return FieldEncryption(key) if key else None

    def add_key(self, version: str, key_bytes: bytes) -> None:
        """Add a key version (for rotation: add new key, keep old)."""
        self._keys[version] = key_bytes


_key_manager = KeyManager()


def get_key_manager() -> KeyManager:
    """Global key manager singleton."""
    return _key_manager


# ── Convenience functions ─────────────────────────────────────────────────────

def encrypt_field(value: str | None) -> str | None:
    """Encrypt a field using the current key. Passthrough if disabled."""
    enc = _key_manager.current_encryptor()
    if not enc:
        return value
    return enc.encrypt(value)


def decrypt_field(value: str | None) -> str | None:
    """Decrypt a field. Passthrough for plaintext values."""
    enc = _key_manager.current_encryptor()
    if not enc:
        return value
    return enc.decrypt(value)


def encrypt_json(data: dict[str, Any], sensitive_fields: list[str]) -> dict[str, Any]:
    """Encrypt specific fields in a JSON-serializable dict."""
    enc = _key_manager.current_encryptor()
    if not enc:
        return data
    return enc.encrypt_dict(data, sensitive_fields)


def decrypt_json(data: dict[str, Any], sensitive_fields: list[str]) -> dict[str, Any]:
    """Decrypt specific fields from an encrypted dict."""
    enc = _key_manager.current_encryptor()
    if not enc:
        return data
    return enc.decrypt_dict(data, sensitive_fields)


# ── Sensitive field registry ──────────────────────────────────────────────────
# Documents which fields are encrypted for KVKK/GDPR compliance reporting.

ENCRYPTED_FIELDS: dict[str, list[str]] = {
    "transactions": ["description", "vendor"],
    "analysis_jobs": [],           # result JSON is too large — use application-level
    "smmm_onay_kayitlari": ["tx_description"],
    "audit_logs": ["request_body"],  # may contain PII
}


def generate_encryption_key() -> str:
    """
    Generate a new 32-byte base64-encoded encryption key.
    Use this to set FIELD_ENCRYPTION_KEY in .env.
    """
    return base64.b64encode(os.urandom(32)).decode("ascii")
