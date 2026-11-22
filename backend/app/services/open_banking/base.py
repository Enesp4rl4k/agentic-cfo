"""
Open Banking Base — OAuth2 flow for Turkish bank APIs.

Turkish Open Banking (BDDK Açık Bankacılık):
  - Regulation: BDDK 15/01/2021 tarihli Open Banking yönetmeliği
  - Standard: Berlin Group NextGenPSD2 uyumlu
  - Sandbox: Her bankanın developer portal'ında mevcut

Supported banks (sandbox + production):
  - Akbank:  https://developer.akbank.com
  - Garanti: https://developer.garantibbva.com.tr
  - İş Bankası: https://developer.isbank.com.tr (beta)

OAuth2 flow:
  1. POST /bank-connections/connect/{bank}  → redirect_url
  2. User authorizes on bank website
  3. GET  /bank-connections/callback?code=...&state=... → token exchange
  4. POST /bank-connections/{id}/sync → fetch transactions

IMPORTANT: Production requires BDDK "Ödeme Hizmeti Sağlayıcısı" (ÖHS) license.
Sandbox access is available for development without a license.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from app.services.ingest.feed import (
    Feed,
    FeedFailed,
    FeedResult,
)

MAX_PAGES = 50

logger = logging.getLogger(__name__)


def why(exc: Exception) -> str:
    """A reason for a person: the status or the kind of failure, never the response body (it may hold anything)."""
    return str(exc) if isinstance(exc, FeedFailed) else f"{type(exc).__name__}"


def response_list(raw: Any, *keys: str) -> list[Any]:
    """The list under the first of `keys` the response HAS (an empty list is a real answer); else the shape is wrong."""
    if isinstance(raw, dict):
        for key in keys:
            if key in raw and isinstance(raw[key], list):
                return raw[key]
    raise FeedFailed("yanıtta işlem listesi yok (beklenmeyen biçim)")


class OpenBankingError(Exception):
    """Base exception for Open Banking errors."""


class BankOAuthConfig:
    """OAuth2 configuration for a specific bank."""

    def __init__(
        self,
        bank_id: str,
        bank_name: str,
        client_id: str,
        client_secret: str,
        auth_url: str,
        token_url: str,
        accounts_url: str,
        transactions_url: str,
        scopes: list[str],
        sandbox: bool = True,
    ) -> None:
        self.bank_id         = bank_id
        self.bank_name       = bank_name
        self.client_id       = client_id
        self.client_secret   = client_secret
        self.auth_url        = auth_url
        self.token_url       = token_url
        self.accounts_url    = accounts_url
        self.transactions_url = transactions_url
        self.scopes          = scopes
        self.sandbox         = sandbox


class OpenBankingClient:
    """
    Generic OAuth2 Open Banking client.

    Handles the OAuth2 authorization code flow, token refresh,
    account listing, and transaction fetching.

    Each bank subclass overrides _parse_transactions() to normalize
    the bank-specific response format to ParsedTransaction dicts.
    """

    def __init__(self, config: BankOAuthConfig) -> None:
        self.config = config
        self._http  = httpx.AsyncClient(timeout=30.0)

    def build_authorization_url(
        self,
        redirect_uri: str,
        state: str | None = None,
    ) -> tuple[str, str]:
        """
        Build the OAuth2 authorization URL for user redirection.

        Returns:
            (auth_url, state) — state should be stored in session for CSRF validation
        """
        if not state:
            state = secrets.token_urlsafe(32)

        # PKCE code challenge (required by some banks)
        code_verifier  = secrets.token_urlsafe(64)
        code_challenge = hashlib.sha256(code_verifier.encode()).hexdigest()

        params = {
            "response_type":         "code",
            "client_id":             self.config.client_id,
            "redirect_uri":          redirect_uri,
            "scope":                 " ".join(self.config.scopes),
            "state":                 state,
            "code_challenge":        code_challenge,
            "code_challenge_method": "S256",
        }

        query = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{self.config.auth_url}?{query}", state

    async def exchange_code_for_tokens(
        self,
        code: str,
        redirect_uri: str,
        code_verifier: str | None = None,
    ) -> dict[str, Any]:
        """
        Exchange authorization code for access + refresh tokens.

        Returns:
            {access_token, refresh_token, expires_in, token_type}
        """
        data: dict[str, str] = {
            "grant_type":   "authorization_code",
            "client_id":    self.config.client_id,
            "client_secret": self.config.client_secret,
            "code":         code,
            "redirect_uri": redirect_uri,
        }
        if code_verifier:
            data["code_verifier"] = code_verifier

        try:
            resp = await self._http.post(self.config.token_url, data=data)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            raise OpenBankingError(f"Token exchange failed: {exc.response.text}") from exc

    async def refresh_access_token(self, refresh_token: str) -> dict[str, Any]:
        """Refresh an expired access token."""
        data = {
            "grant_type":    "refresh_token",
            "client_id":     self.config.client_id,
            "client_secret": self.config.client_secret,
            "refresh_token": refresh_token,
        }
        try:
            resp = await self._http.post(self.config.token_url, data=data)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            raise OpenBankingError(f"Token refresh failed: {exc.response.text}") from exc

    async def get_accounts(self, access_token: str) -> list[dict[str, Any]]:
        """Fetch the list of accounts for the authorized user."""
        try:
            resp = await self._http.get(
                self.config.accounts_url,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            resp.raise_for_status()
            return self._parse_accounts(resp.json())
        except httpx.HTTPStatusError as exc:
            raise OpenBankingError(f"Account fetch failed: {exc.response.text}") from exc

    async def get_transactions(
        self,
        access_token: str,
        account_id: str,
        start_date: str,   # YYYY-MM-DD
        end_date: str,     # YYYY-MM-DD
    ) -> FeedResult:
        """
        Fetch the transactions of an account, every page, and say how it went.

        Returns a `FeedResult`: one row per fetched item (an unknown amount, direction, date or currency is
        None and the row waits for a person), the counts, and:
          - `failed`  when the first page could not be read (outage, refusal, malformed JSON, unexpected
            shape): nothing is returned, and an outage is never "no transactions";
          - `partial` when a later page failed or the page limit was reached: the rows fetched are returned and
            the result does not cover the period.
        """
        feed = Feed(f"{self.config.bank_id}_open_banking")
        first_url = self.config.transactions_url.format(account_id=account_id)
        url: str | None = first_url
        params: dict[str, str] | None = {"startDate": start_date, "endDate": end_date}
        host = str(urlparse(first_url).netloc)
        page = 0
        while url and page < MAX_PAGES:
            page += 1
            try:
                resp = await self._http.get(url, headers={"Authorization": f"Bearer {access_token}"}, params=params)
                if resp.status_code != 200:
                    raise FeedFailed(f"banka {resp.status_code} yanıtı verdi")
                payload = resp.json()
                self._parse_transactions(payload, feed)
            except (httpx.HTTPError, ValueError, FeedFailed) as exc:
                reason = f"{page}. sayfa alınamadı: {why(exc)}"
                if page == 1:
                    return feed.fail(reason)
                feed.partial = reason
                break
            url = self._next_page(payload, url, host)
            params = None
        else:
            if url:
                feed.partial = f"sayfa sınırına ulaşıldı ({MAX_PAGES}); işlemlerin devamı çekilmedi"
        return feed.result()

    @staticmethod
    def _next_page(payload: Any, current: str, host: str) -> str | None:
        """The next page's URL (Berlin Group `_links.next.href`), only ever on the bank's own host."""
        link = ((payload.get("_links") or {}).get("next") or {}).get("href") if isinstance(payload, dict) else None
        if not link:
            return None
        nxt = urljoin(current, str(link))
        return nxt if urlparse(nxt).netloc == host else None

    def _parse_accounts(self, raw: Any) -> list[dict[str, Any]]:
        """Override in subclasses to handle bank-specific account format."""
        if isinstance(raw, list):
            return raw
        return raw.get("accounts", raw.get("data", []))

    def _parse_transactions(self, raw: Any, feed: Feed) -> None:
        """
        Override in subclasses: add one row to `feed` per transaction of the bank-specific response, through
        `Feed.each` / `Feed.add` (nothing is skipped or defaulted). Raise `FeedFailed` when the response does
        not have the shape the bank documents.
        """
        raise NotImplementedError("each bank documents its own response shape")

    async def close(self) -> None:
        await self._http.aclose()
