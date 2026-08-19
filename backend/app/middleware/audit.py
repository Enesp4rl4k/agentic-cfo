"""
Audit Log Middleware — FastAPI Starlette middleware.

Records every mutating request (POST/PUT/PATCH/DELETE) to the audit_logs table.

Behavior:
  - Reads the request body BEFORE passing to the route handler (body is re-injected)
  - Extracts user identity from JWT token (best-effort, no DB hit)
  - Strips sensitive fields from request body (password, token, api_key, secret)
  - Records response status and duration
  - Skips: GET/HEAD/OPTIONS, health checks, docs, static files
  - Non-fatal: audit failure must not break business logic

Fix applied (SEC-6):
  The original implementation attempted to read request.stream() AFTER the response
  was already sent, which always yields empty bytes because the ASGI body had
  already been consumed. The fix buffers the body before calling the route handler
  and re-injects it so the route can still read it normally.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from starlette.datastructures import Headers
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import Message

logger = logging.getLogger(__name__)

_SKIP_PATHS    = {"/health", "/docs", "/redoc", "/openapi.json", "/favicon.ico"}
_SKIP_PREFIXES = ("/static", "/_next")
_AUDIT_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

_SENSITIVE_FIELDS = {
    "password", "hashed_password", "token", "access_token", "refresh_token",
    "api_key", "secret", "secret_key", "authorization",
}

# Max body size to store in the audit log (avoid huge blobs in DB)
_MAX_BODY_LOG_BYTES = 8 * 1024  # 8 KB


def _redact_body(body: dict[str, Any]) -> dict[str, Any]:
    return {
        k: "***REDACTED***" if k.lower() in _SENSITIVE_FIELDS else v
        for k, v in body.items()
    }


def _extract_user(request: Request) -> tuple[str | None, str | None, str | None]:
    """Extract (user_id, email, role) from JWT. Returns (None,None,None) on failure."""
    try:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            from app.services.auth import decode_token
            payload = decode_token(auth[7:])
            return payload.get("sub"), payload.get("email"), payload.get("role")
    except Exception:
        pass
    return None, None, None


class AuditLogMiddleware(BaseHTTPMiddleware):
    """
    ASGI middleware that writes an AuditLog row for every mutating request.

    Body is buffered before the route handler runs, then re-injected so the
    route can still read it. The audit write happens in a background task.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        # Fast-path skips
        if request.method not in _AUDIT_METHODS:
            return await call_next(request)

        path = request.url.path
        if path in _SKIP_PATHS:
            return await call_next(request)
        if any(path.startswith(p) for p in _SKIP_PREFIXES):
            return await call_next(request)

        # ── Buffer request body BEFORE the route handler consumes it ──────────
        raw_body: bytes = b""
        try:
            raw_body = await request.body()
        except Exception:
            pass

        # Re-inject body so route handlers can still read it
        async def _receive() -> Message:
            return {"type": "http.request", "body": raw_body, "more_body": False}

        request = Request(request.scope, receive=_receive)

        # ── Time the request ──────────────────────────────────────────────────
        start = time.monotonic()
        response = await call_next(request)
        duration_ms = int((time.monotonic() - start) * 1000)

        # ── Parse body for audit log ──────────────────────────────────────────
        request_body: dict | None = None
        try:
            if raw_body and len(raw_body) <= _MAX_BODY_LOG_BYTES:
                content_type = request.headers.get("content-type", "")
                if "application/json" in content_type:
                    request_body = _redact_body(json.loads(raw_body))
        except Exception:
            pass

        user_id, user_email, user_role = _extract_user(request)

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
        try:
            from app.database import get_session_factory, engine
            from app.models.audit_log import AuditLog

            async with get_session_factory(engine())() as db:
                log = AuditLog(**data)
                db.add(log)
                await db.commit()
        except Exception as exc:
            logger.warning("Audit log write failed: %s", exc)
