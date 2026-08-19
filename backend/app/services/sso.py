"""
SSO Service — OAuth2 / OIDC entegrasyonu

Desteklenen provider'lar:
  - Microsoft Entra ID (Azure AD) — kurumsal Türkiye şirketleri için
  - Google Workspace                — startup'lar için
  - GitHub                          — geliştirici hesapları için (opsiyonel)

Akış (PKCE + Authorization Code):
  1. GET /auth/sso/{provider}/login   → provider redirect URL döner
  2. Kullanıcı provider'da oturum açar
  3. Provider → GET /auth/sso/{provider}/callback?code=...
  4. Backend: code → access_token → kullanıcı profili
  5. Kullanıcı DB'de yoksa otomatik oluştur (just-in-time provisioning)
  6. Backend JWT üret → frontend'e yönlendir

Güvenlik:
  - PKCE (code verifier/challenge) — state poisoning'e karşı
  - state parametresi — CSRF koruması
  - Redis'te state TTL=10 dakika
  - Provider domain allowlist (org bazında konfigüre edilebilir)

DDIA: SSO state immutable event olarak Redis'te saklanır.
Callback sadece bir kez işlenir (idempotency).
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ── Provider config ───────────────────────────────────────────────────────────

@dataclass
class OAuthProvider:
    name:            str
    client_id:       str
    client_secret:   str
    authorization_url: str
    token_url:       str
    userinfo_url:    str
    scopes:          list[str]
    enabled:         bool = False


def _build_providers(settings: Any) -> dict[str, OAuthProvider]:
    """Build provider configs from settings. Disabled if credentials missing."""
    providers: dict[str, OAuthProvider] = {}

    # ── Microsoft Entra ID ────────────────────────────────────────────────────
    tenant = getattr(settings, "azure_tenant_id", "") or "common"
    providers["microsoft"] = OAuthProvider(
        name              = "microsoft",
        client_id         = getattr(settings, "azure_client_id", ""),
        client_secret     = getattr(settings, "azure_client_secret", ""),
        authorization_url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize",
        token_url         = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
        userinfo_url      = "https://graph.microsoft.com/v1.0/me",
        scopes            = ["openid", "profile", "email", "User.Read"],
        enabled           = bool(getattr(settings, "azure_client_id", "")),
    )

    # ── Google Workspace ──────────────────────────────────────────────────────
    providers["google"] = OAuthProvider(
        name              = "google",
        client_id         = getattr(settings, "google_client_id", ""),
        client_secret     = getattr(settings, "google_client_secret", ""),
        authorization_url = "https://accounts.google.com/o/oauth2/v2/auth",
        token_url         = "https://oauth2.googleapis.com/token",
        userinfo_url      = "https://www.googleapis.com/oauth2/v3/userinfo",
        scopes            = ["openid", "email", "profile"],
        enabled           = bool(getattr(settings, "google_client_id", "")),
    )

    # ── GitHub ────────────────────────────────────────────────────────────────
    providers["github"] = OAuthProvider(
        name              = "github",
        client_id         = getattr(settings, "github_client_id", ""),
        client_secret     = getattr(settings, "github_client_secret", ""),
        authorization_url = "https://github.com/login/oauth/authorize",
        token_url         = "https://github.com/login/oauth/access_token",
        userinfo_url      = "https://api.github.com/user",
        scopes            = ["read:user", "user:email"],
        enabled           = bool(getattr(settings, "github_client_id", "")),
    )

    return providers


# ── PKCE helpers ──────────────────────────────────────────────────────────────

def _generate_pkce() -> tuple[str, str]:
    """Generate PKCE code_verifier + code_challenge (S256)."""
    verifier  = base64.urlsafe_b64encode(os.urandom(40)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


def _generate_state() -> str:
    """Random 32-byte hex state for CSRF protection."""
    return secrets.token_hex(32)


# ── SSO state (Redis-backed) ──────────────────────────────────────────────────

_STATE_TTL = 600  # 10 minutes

async def _save_state(state: str, data: dict) -> None:
    """Persist OAuth state in Redis (with TTL) or in-memory fallback."""
    try:
        from app.services.company_context import _get_redis
        redis = await _get_redis()
        if redis:
            await redis.setex(f"sso_state:{state}", _STATE_TTL, json.dumps(data))
            return
    except Exception:
        pass
    # In-memory fallback (single-process dev only)
    _STATE_STORE[state] = (data, datetime.now(timezone.utc).timestamp() + _STATE_TTL)


async def _load_state(state: str) -> dict | None:
    """Load and DELETE OAuth state (single-use)."""
    try:
        from app.services.company_context import _get_redis
        redis = await _get_redis()
        if redis:
            raw = await redis.getdel(f"sso_state:{state}")
            return json.loads(raw) if raw else None
    except Exception:
        pass
    # In-memory fallback
    entry = _STATE_STORE.pop(state, None)
    if not entry:
        return None
    data, expires = entry
    if datetime.now(timezone.utc).timestamp() > expires:
        return None
    return data


_STATE_STORE: dict[str, tuple[dict, float]] = {}  # in-memory fallback


# ── Userinfo normalization ────────────────────────────────────────────────────

@dataclass
class OAuthUser:
    """Normalized user profile from any OAuth provider."""
    provider:     str
    provider_id:  str
    email:        str
    full_name:    str
    avatar_url:   str | None = None
    domain:       str | None = None    # workspace domain (for allowlisting)
    raw:          dict = field(default_factory=dict)


def _normalize_microsoft(data: dict) -> OAuthUser:
    email = data.get("mail") or data.get("userPrincipalName", "")
    name  = data.get("displayName") or data.get("givenName", "")
    return OAuthUser(
        provider    = "microsoft",
        provider_id = data.get("id", ""),
        email       = email,
        full_name   = name,
        domain      = email.split("@")[1] if "@" in email else None,
        raw         = data,
    )


def _normalize_google(data: dict) -> OAuthUser:
    email = data.get("email", "")
    return OAuthUser(
        provider    = "google",
        provider_id = data.get("sub", ""),
        email       = email,
        full_name   = data.get("name", ""),
        avatar_url  = data.get("picture"),
        domain      = data.get("hd") or (email.split("@")[1] if "@" in email else None),
        raw         = data,
    )


def _normalize_github(data: dict, emails: list[dict] | None = None) -> OAuthUser:
    email = data.get("email", "")
    if not email and emails:
        primary = next((e["email"] for e in emails if e.get("primary")), "")
        email   = primary
    return OAuthUser(
        provider    = "github",
        provider_id = str(data.get("id", "")),
        email       = email,
        full_name   = data.get("name") or data.get("login", ""),
        avatar_url  = data.get("avatar_url"),
        domain      = email.split("@")[1] if "@" in email else None,
        raw         = data,
    )


# ── Main SSO service ──────────────────────────────────────────────────────────

class SSOService:
    """
    OAuth2 / OIDC SSO service.

    Handles:
    - Authorization URL generation (with PKCE + state)
    - Callback handling (code exchange → user profile)
    - JIT user provisioning
    """

    def __init__(self, settings: Any) -> None:
        self._settings  = settings
        self._providers = _build_providers(settings)

    def get_enabled_providers(self) -> list[str]:
        """Return list of configured/enabled provider names."""
        return [name for name, p in self._providers.items() if p.enabled]

    def get_provider(self, name: str) -> OAuthProvider:
        p = self._providers.get(name)
        if not p:
            raise ValueError(f"Unknown SSO provider: {name}")
        if not p.enabled:
            raise ValueError(f"SSO provider '{name}' is not configured")
        return p

    async def get_authorization_url(
        self,
        provider_name: str,
        redirect_uri:  str,
        extra_state:   dict | None = None,
    ) -> tuple[str, str]:
        """
        Build authorization URL and save PKCE state.

        Returns (authorization_url, state).
        """
        provider = self.get_provider(provider_name)
        state    = _generate_state()
        verifier, challenge = _generate_pkce()

        # Save state for callback verification
        await _save_state(state, {
            "provider":     provider_name,
            "verifier":     verifier,
            "redirect_uri": redirect_uri,
            **(extra_state or {}),
        })

        params: dict[str, str] = {
            "client_id":             provider.client_id,
            "response_type":         "code",
            "redirect_uri":          redirect_uri,
            "scope":                 " ".join(provider.scopes),
            "state":                 state,
            "code_challenge":        challenge,
            "code_challenge_method": "S256",
        }

        # Provider-specific extras
        if provider_name == "google":
            params["access_type"] = "offline"
            params["prompt"]      = "select_account"
        elif provider_name == "microsoft":
            params["prompt"] = "select_account"

        url = provider.authorization_url + "?" + urllib.parse.urlencode(params)
        return url, state

    async def handle_callback(
        self,
        provider_name: str,
        code:          str,
        state:         str,
    ) -> OAuthUser:
        """
        Exchange authorization code for tokens and retrieve user profile.

        Raises ValueError on CSRF/PKCE failures.
        """
        # Load and verify state
        state_data = await _load_state(state)
        if not state_data:
            raise ValueError("Invalid or expired OAuth state. Please try again.")
        if state_data.get("provider") != provider_name:
            raise ValueError("OAuth state provider mismatch.")

        provider     = self.get_provider(provider_name)
        verifier     = state_data["verifier"]
        redirect_uri = state_data["redirect_uri"]

        # Exchange code for tokens
        token_data = await self._exchange_code(
            provider, code, verifier, redirect_uri
        )
        access_token = token_data.get("access_token", "")

        # Fetch user profile
        user = await self._fetch_userinfo(provider_name, provider, access_token)
        return user

    async def _exchange_code(
        self,
        provider:     OAuthProvider,
        code:         str,
        verifier:     str,
        redirect_uri: str,
    ) -> dict:
        """POST code to token endpoint, return token response."""
        payload = {
            "grant_type":    "authorization_code",
            "client_id":     provider.client_id,
            "client_secret": provider.client_secret,
            "code":          code,
            "redirect_uri":  redirect_uri,
            "code_verifier": verifier,
        }

        async with httpx.AsyncClient(timeout=15) as client:
            headers = {"Accept": "application/json"}
            if provider.name == "github":
                headers["Accept"] = "application/json"

            resp = await client.post(
                provider.token_url,
                data=payload,
                headers=headers,
            )
            if resp.status_code != 200:
                logger.error(
                    "Token exchange failed: provider=%s status=%d body=%s",
                    provider.name, resp.status_code, resp.text[:200]
                )
                raise ValueError(f"Token exchange failed: {resp.status_code}")

            return resp.json()

    async def _fetch_userinfo(
        self,
        provider_name: str,
        provider:      OAuthProvider,
        access_token:  str,
    ) -> OAuthUser:
        """Fetch user profile from provider's userinfo endpoint."""
        headers = {"Authorization": f"Bearer {access_token}"}
        if provider_name == "github":
            headers["Accept"] = "application/vnd.github.v3+json"

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(provider.userinfo_url, headers=headers)
            if resp.status_code != 200:
                raise ValueError(f"Userinfo fetch failed: {resp.status_code}")
            data = resp.json()

            # GitHub: fetch emails separately if not in profile
            emails = None
            if provider_name == "github" and not data.get("email"):
                email_resp = await client.get(
                    "https://api.github.com/user/emails",
                    headers=headers,
                )
                if email_resp.status_code == 200:
                    emails = email_resp.json()

        normalizers = {
            "microsoft": _normalize_microsoft,
            "google":    _normalize_google,
            "github":    lambda d: _normalize_github(d, emails),
        }
        normalize = normalizers.get(provider_name)
        if not normalize:
            raise ValueError(f"No normalizer for provider: {provider_name}")
        return normalize(data)


# ── JIT user provisioning ─────────────────────────────────────────────────────

async def provision_sso_user(
    oauth_user: OAuthUser,
    db:         Any,
) -> Any:
    """
    Find or create a user from an OAuth profile (Just-In-Time provisioning).

    Rules:
    1. Look up existing user by email
    2. If found → update sso_provider/sso_id, return user
    3. If not found → create new user (role=ANALYST, no password)
    """
    from sqlalchemy import select
    from app.models.user import User, UserRole

    if not oauth_user.email:
        raise ValueError("OAuth provider did not return an email address")

    # Find existing user
    result = await db.execute(
        select(User).where(User.email == oauth_user.email.lower())
    )
    user = result.scalar_one_or_none()

    now = datetime.now(timezone.utc)

    if user:
        # Update SSO metadata
        user.sso_provider = oauth_user.provider
        user.sso_id       = oauth_user.provider_id
        user.last_login   = now
        if not user.full_name and oauth_user.full_name:
            user.full_name = oauth_user.full_name
        await db.commit()
        return user

    # Create new user (JIT provisioning)
    new_user = User(
        email         = oauth_user.email.lower(),
        full_name     = oauth_user.full_name or oauth_user.email.split("@")[0],
        hashed_password = "",      # No password — SSO only
        role          = UserRole.ANALYST,
        is_active     = True,
        sso_provider  = oauth_user.provider,
        sso_id        = oauth_user.provider_id,
        last_login    = now,
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    logger.info(
        "JIT SSO user provisioned: email=%s provider=%s",
        oauth_user.email, oauth_user.provider
    )
    return new_user


# ── Singleton ─────────────────────────────────────────────────────────────────

_sso_service: SSOService | None = None


def get_sso_service() -> SSOService:
    """Global SSO service singleton."""
    global _sso_service
    if _sso_service is None:
        from app.config import get_settings
        _sso_service = SSOService(get_settings())
    return _sso_service
