"""Mask personal data and credentials in a log line before it is written.

Nine call sites log an address (`User logged in: %s`, `Invite queued: ... -> %s`), and an exception
text can carry one, a bearer token or an IBAN. Fixing each site would leave the next one unguarded, so
the formatters call `redact` on every string they emit. It keeps enough to tell two lines apart: the
first character and the domain of an address, the country and last four digits of an IBAN.
"""

from __future__ import annotations

import logging
import re

_EMAIL = re.compile(r"\b([A-Za-z0-9._%+\-])[A-Za-z0-9._%+\-]*@([A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,})\b")
_IBAN = re.compile(r"\b(TR)\d{2}(?:[ ]?\d{4}){5}[ ]?(\d{2})\b", re.IGNORECASE)
_BEARER = re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/\-]{12,}=*")
_SECRET_PAIR = re.compile(
    r"(?i)\b(password|passwd|secret|api[_-]?key|access[_-]?token|refresh[_-]?token|authorization)(['\"]?\s*[=:]\s*['\"]?)[^\s,;'\"&]{4,}"
)


def redact(text: str) -> str:
    """The text with e-mail addresses, IBANs, bearer tokens and `key=value` secrets masked."""
    if not text:
        return text
    text = _EMAIL.sub(lambda m: f"{m.group(1)}***@{m.group(2)}", text)
    text = _IBAN.sub(lambda m: f"{m.group(1).upper()}**…{m.group(2)}", text)
    text = _BEARER.sub(r"\1 [redacted]", text)
    return _SECRET_PAIR.sub(lambda m: f"{m.group(1)}{m.group(2)}[redacted]", text)


class RedactingFilter(logging.Filter):
    """Handler filter for the plain-text format: mask the rendered message and the traceback."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = None
        if record.exc_text:
            record.exc_text = redact(record.exc_text)
        return True
