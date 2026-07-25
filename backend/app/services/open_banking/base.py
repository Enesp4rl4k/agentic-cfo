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
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any

import httpx

logger = logging.getLogger(__name__)


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
    ) -> list[dict[str, Any]]:
        """
        Fetch transactions for an account.

        Returns normalized list of transaction dicts compatible with
        the CFO pipeline's data ingestion format.
        """
        url = self.config.transactions_url.format(account_id=account_id)
        try:
            resp = await self._http.get(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                params={"startDate": start_date, "endDate": end_date},
            )
            resp.raise_for_status()
            return self._parse_transactions(resp.json())
        except httpx.HTTPStatusError as exc:
            raise OpenBankingError(f"Transaction fetch failed: {exc.response.text}") from exc

    def _parse_accounts(self, raw: Any) -> list[dict[str, Any]]:
        """Override in subclasses to handle bank-specific account format."""
        if isinstance(raw, list):
            return raw
        return raw.get("accounts", raw.get("data", []))

    def _parse_transactions(self, raw: Any) -> list[dict[str, Any]]:
        """
        Override in subclasses to normalize bank-specific transaction format
        to the standard CFO pipeline format:
          {amount_cents, type, date, description, currency, reference}
        """
        txs = raw if isinstance(raw, list) else raw.get("transactions", raw.get("data", []))
        return txs

    async def close(self) -> None:
        await self._http.aclose()
