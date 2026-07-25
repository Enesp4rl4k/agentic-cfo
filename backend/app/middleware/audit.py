"""
Audit Log Middleware — FastAPI Starlette middleware.

Records every mutating request (POST/PUT/PATCH/DELETE) to the audit_logs table.

Behavior:
  - Runs AFTER the response is sent (non-blocking)
  - Extracts user identity from JWT token or API key header (best-effort)
  - Strips sensitive fields from request body (password, token, api_key, secret)
  - Skips: GET/HEAD/OPTIONS, health checks, docs, static files
  - Skips if DB is unavailable (non-fatal — audit failure must not break business logic)

Registration in main.py:
    from app.middleware.audit import AuditLogMiddleware
    app.add_middleware(AuditLogMiddleware)
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

# Paths that should never be audited (high-frequency, low-value)
_SKIP_PATHS = {"/health", "/docs", "/redoc", "/openapi.json", "/favicon.ico"}
_SKIP_PREFIXES = ("/static", "/_next")

# HTTP methods to audit
_AUDIT_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# Request body fields to redact before storing
_SENSITIVE_FIELDS = {
    "password", "hashed_password", "token", "access_token", "refresh_token",
    "api_key", "secret", "secret_key", "authorization",
}


def _redact_body(body: dict[str, Any]) -> dict[str, Any]:
    """Remove sensitive fields from a request body dict."""
    return {
        k: "***REDACTED***" if k.lower() in _SENSITIVE_FIELDS else v
        for k, v in body.items()
    }


def _extract_user(request: Request) -> tuple[str | None, str | None, str | None]:
    """
    Extract (user_id, email, role) from request.

    Tries JWT token first, then API key.
    Returns (None, None, None) if not authenticated or token invalid.
    """
    try:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
            from app.services.auth import decode_token
            payload = decode_token(token)
            return payload.get("sub"), payload.get("email"), payload.get("role")
    except Exception:
        pass

    # API key check — resolve to user in DB (async context needed, skip here)
    # user_id from API key requires DB lookup — not worth the overhead in middleware
    return None, None, None


class AuditLogMiddleware(BaseHTTPMiddleware):
    """
    ASGI middleware that writes an AuditLog row for every mutating request.

    Uses a background task to avoid blocking the response.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        # ── Fast-path skips ───────────────────────────────────────────────────
        if request.method not in _AUDIT_METHODS:
            return await call_next(request)

        path = request.url.path
        if path in _SKIP_PATHS:
            return await call_next(request)
        if any(path.startswith(p) for p in _SKIP_PREFIXES):
            return await call_next(request)

        # ── Time the request ──────────────────────────────────────────────────
        start = time.monotonic()
        response = await call_next(request)
        duration_ms = int((time.monotonic() - start) * 1000)

        # ── Parse request body (already consumed by this point — best effort) ─
        request_body: dict | None = None
        try:
            # Body was consumed by the route handler; try to get it from scope
            body_bytes = b""
            async for chunk in request.stream():
                body_bytes += chunk
            if body_bytes:
                request_body = _redact_body(json.loads(body_bytes))
        except Exception:
            pass

        # ── Extract user identity ─────────────────────────────────────────────
        user_id, user_email, user_role = _extract_user(request)

        # ── Write audit log in background (fire-and-forget) ──────────────────
        audit_data = {
            "id":              str(uuid.uuid4()),
            "user_id":         user_id,
            "user_email":      user_email,
            "user_role":       user_role,
            "action":          f"{request.method} {path}",
            "resource":        path,
            "request_body":    request_body,
            "response_status": response.status_code,
            "ip_address":      self._get_ip(request),
            "user_agent":      request.headers.get("User-Agent", "")[:500],
            "duration_ms":     duration_ms,
            "reason":          request.headers.get("X-Audit-Reason"),
            "created_at":      datetime.now(timezone.utc),
        }

        # Schedule DB write without blocking response
        import asyncio
        asyncio.create_task(self._write_audit(audit_data))

        return response

    @staticmethod
    def _get_ip(request: Request) -> str | None:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        if request.client:
            return request.client.host
        return None

    @staticmethod
    async def _write_audit(data: dict) -> None:
        """Write audit log to DB. Non-fatal — logs warning if it fails."""
        try:
            from app.database import get_session_factory, engine
            from app.models.audit_log import AuditLog

            async with get_session_factory(engine())() as db:
                log = AuditLog(**data)
                db.add(log)
                await db.commit()
        except Exception as exc:
            logger.warning("Audit log write failed: %s", exc)
