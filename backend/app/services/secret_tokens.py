"""One way to mint and store a single-use secret that travels in a link.

An invitation token and a password-reset token are bearer secrets: whoever holds the
link may act. The database keeps only a SHA-256 digest, so a copy of the table (a
backup, a read-only SQL leak) does not contain a usable link. A 256-bit random token
needs no salt or slow hash; the digest is what every lookup compares.

`new_token()` returns the raw token (goes into the e-mailed link, never stored) and
its digest (stored). `hash_token(raw)` is the lookup key for a token a caller presents.
"""
from __future__ import annotations

import hashlib
import secrets

TOKEN_BYTES = 32


def hash_token(raw: str) -> str:
    """The stored form of a presented token: 64 hex characters."""
    return hashlib.sha256(raw.strip().encode("utf-8")).hexdigest()


def new_token() -> tuple[str, str]:
    """(raw token for the link, digest to store)."""
    raw = secrets.token_hex(TOKEN_BYTES)
    return raw, hash_token(raw)
