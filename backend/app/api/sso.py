"""
SSO API — OAuth2 / OIDC endpoints

GET  /auth/sso/providers             → Aktif provider listesi
GET  /auth/sso/{provider}/login      → Authorization URL al
GET  /auth/sso/{provider}/callback   → Code exchange → JWT token

Akış:
  1. Frontend: GET /auth/sso/google/login?redirect_uri=...
     → { "authorization_url": "https://accounts.google.com/..." }
  2. Frontend: kullanıcıyı authorization_url'e yönlendir
  3. Google/Microsoft: /auth/sso/google/callback?code=...&state=... çağırır
  4. Backend: JWT üretir → frontend'e yönlendirir
"""
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.models.user import User

router = APIRouter()
logger = logging.getLogger(__name__)


def _frontend_url(settings: Any) -> str:
    """Return the configured frontend base URL."""
    return getattr(settings, "frontend_url", "http://localhost:3000")


@router.get("/auth/sso/providers")
async def list_sso_providers() -> dict[str, Any]:
    """
    List configured and enabled SSO providers.
    Frontend uses this to show/hide SSO login buttons.
    """
    from app.services.sso import get_sso_service
    svc = get_sso_service()
    return {
        "data": {
            "providers": svc.get_enabled_providers(),
            "count":     len(svc.get_enabled_providers()),
        },
        "error": None,
    }


@router.get("/auth/sso/{provider}/login")
async def sso_login(
    provider:     str,
    redirect_uri: str = Query(
        default="",
        description="Where to redirect after login (defaults to frontend /auth/callback)"
    ),
) -> dict[str, Any]:
    """
    Generate the authorization URL for the given SSO provider.

    Frontend should redirect the user to the returned `authorization_url`.
    """
    from app.config import get_settings
    from app.services.sso import get_sso_service

    settings = get_settings()

    # Default redirect URI: backend callback endpoint
    if not redirect_uri:
        base     = getattr(settings, "backend_url", "http://localhost:8000")
        redirect_uri = f"{base}/api/v1/auth/sso/{provider}/callback"

    try:
        svc = get_sso_service()
        url, state = await svc.get_authorization_url(
            provider_name = provider,
            redirect_uri  = redirect_uri,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {
        "data": {
            "authorization_url": url,
            "state":             state,
            "provider":          provider,
        },
        "error": None,
    }


@router.get("/auth/sso/{provider}/callback")
async def sso_callback(
    provider: str,
    code:     str   = Query(..., description="Authorization code from provider"),
    state:    str   = Query(..., description="CSRF state parameter"),
    error:    str | None = Query(default=None),
    db:       AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """
    OAuth2 callback endpoint.

    Called by the provider after the user authenticates.
    Exchanges the code for tokens, provisions the user, and redirects
    to the frontend with a JWT token in the query string.

    Frontend should:
      1. Extract the token from URL: ?token=...
      2. Store in localStorage as the session token
      3. Redirect to dashboard
    """
    from app.config import get_settings
    from app.services.auth import create_access_token, create_refresh_token
    from app.services.sso import get_sso_service, provision_sso_user

    settings     = get_settings()
    frontend_url = _frontend_url(settings)
    error_url    = f"{frontend_url}/auth/login?error=sso_failed"

    # Provider declined
    if error:
        logger.warning("SSO provider error: provider=%s error=%s", provider, error)
        return RedirectResponse(url=f"{error_url}&reason={error}")

    try:
        svc       = get_sso_service()
        oauth_user = await svc.handle_callback(provider, code, state)
    except ValueError as exc:
        logger.warning("SSO callback validation failed: %s", exc)
        return RedirectResponse(url=f"{error_url}&reason=state_invalid")
    except Exception as exc:
        logger.error("SSO callback error: %s", exc)
        return RedirectResponse(url=f"{error_url}&reason=provider_error")

    try:
        user = await provision_sso_user(oauth_user, db)
    except Exception as exc:
        logger.error("SSO user provisioning failed: %s", exc)
        return RedirectResponse(url=f"{error_url}&reason=provisioning_failed")

    # Generate JWT tokens
    access_token  = create_access_token(
        user_id = str(user.id),
        email   = user.email,
        role    = str(user.role),
    )
    refresh_token = create_refresh_token(
        user_id = str(user.id),
        email   = user.email,
    )

    # Redirect to frontend with tokens
    params = urlencode({
        "access_token":  access_token,
        "refresh_token": refresh_token,
        "provider":      provider,
    })
    redirect_url = f"{frontend_url}/auth/sso-callback?{params}"
    return RedirectResponse(url=redirect_url, status_code=302)


@router.get("/auth/sso/me/connections")
async def list_sso_connections(
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Return the current user's SSO connection info.
    Used in Settings → Security to show which providers are linked.
    """
    return {
        "data": {
            "sso_provider": getattr(current_user, "sso_provider", None),
            "sso_id":       getattr(current_user, "sso_id", None),
            "has_password": bool(getattr(current_user, "hashed_password", "")),
        },
        "error": None,
    }
