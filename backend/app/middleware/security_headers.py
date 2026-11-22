"""
Security Headers Middleware — OWASP Top 10 Hardening.

Injects defense-in-depth HTTP headers on all API and server responses:
  - X-Content-Type-Options: nosniff
  - X-Frame-Options: DENY
  - X-XSS-Protection: 1; mode=block
  - Strict-Transport-Security: max-age=31536000; includeSubDomains; preload
  - Referrer-Policy: strict-origin-when-cross-origin
  - Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=()
  - Content-Security-Policy (CSP): safe API baseline
  - Cross-Origin-Opener-Policy: same-origin
"""
from __future__ import annotations

import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

DEFAULT_SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains; preload",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    # The API serves JSON and file downloads, never a page: nothing may load, frame or be based here.
    # (The docstring above promised a CSP; none was ever set.) FastAPI's own docs pages need scripts and
    # are exempt below.
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
}

# Swagger UI and ReDoc load their scripts from a CDN and run inline code: the API CSP would blank them.
_DOCS_PATHS = ("/docs", "/redoc")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adds OWASP-compliant security headers to every response."""

    def __init__(self, app, custom_headers: dict[str, str] | None = None):
        super().__init__(app)
        self.headers = {**DEFAULT_SECURITY_HEADERS, **(custom_headers or {})}

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        docs_page = request.url.path.startswith(_DOCS_PATHS)
        for header, value in self.headers.items():
            if header == "Content-Security-Policy" and docs_page:
                continue
            # Don't overwrite if handler explicitly set it
            if header not in response.headers:
                response.headers[header] = value
        return response
