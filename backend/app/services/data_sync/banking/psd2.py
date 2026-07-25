"""
Open Banking PSD2 sync clients for Turkish banks.

Handles:
  - OAuth2 token management
  - Account information aggregation
  - Transaction fetching with pagination
  - Rate limiting + retry logic
  - Balance sync

Supported banks:
  - Garanti BBVA: https://developer.garantibbva.com.tr
  - Akbank: https://developer.akbank.com
"""
from __future__ import annotations

import hashlib
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from pydantic import ValidationError

from app.services.data_sync.schemas import (
    SyncSourceType,
    SyncTransaction,
    SyncBatch,
    TransactionType,
)

logger = logging.getLogger(__name__)


class PSD2BankClient:
    """Base class for PSD2 Open Banking API clients."""

    bank_name: str = ""
    auth_url: str = ""
    api_base: str = ""
    rate_limit_per_minute: int = 100

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        sandbox_mode: bool = True,
    ):
        """
        Initialize PSD2 bank client.

        Args:
            client_id: OAuth2 client ID
            client_secret: OAuth2 client secret
            sandbox_mode: Use sandbox API if True
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.sandbox_mode = sandbox_mode

        self._access_token: Optional[str] = None
        self._token_expires_at: Optional[datetime] = None
        self._rate_limit_reset: datetime = datetime.now(timezone.utc)

    async def _get_access_token(self) -> str:
        """Obtain OAuth2 access token."""
        raise NotImplementedError

    async def _ensure_token(self) -> str:
        """Ensure valid access token, refresh if needed."""
        if (
            self._access_token
            and self._token_expires_at
            and datetime.now(timezone.utc) < self._token_expires_at - timedelta(minutes=5)
        ):
            return self._access_token

        return await self._get_access_token()

    async def _api_call(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict] = None,
        json_data: Optional[dict] = None,
        retry_count: int = 3,
    ) -> dict:
        """Make API call with rate limit + retry logic."""
        # Respect rate limit
        now = datetime.now(timezone.utc)
        if now < self._rate_limit_reset:
            sleep_time = (self._rate_limit_reset - now).total_seconds()
            logger.warning(f"{self.bank_name} rate limit: sleeping {sleep_time:.1f}s")
            time.sleep(min(sleep_time, 1.0))

        token = await self._ensure_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        url = f"{self.api_base}/{endpoint}"

        for attempt in range(retry_count):
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.request(
                        method,
                        url,
                        params=params,
                        json=json_data,
                        headers=headers,
                    )

                    # Update rate limit
                    if "X-RateLimit-Reset" in resp.headers:
                        reset_epoch = int(resp.headers["X-RateLimit-Reset"])
                        self._rate_limit_reset = datetime.fromtimestamp(
                            reset_epoch, tz=timezone.utc
                        )

                    if resp.status_code == 429:
                        backoff = 2 ** attempt
                        logger.warning(
                            f"{self.bank_name} rate limited (attempt {attempt + 1}), "
                            f"backing off {backoff}s"
                        )
                        time.sleep(backoff)
                        continue

                    resp.raise_for_status()
                    return resp.json()

            except httpx.RequestError as e:
                if attempt == retry_count - 1:
                    logger.error(f"{self.bank_name} API call failed: {e}")
                    raise
                backoff = 2 ** attempt
                logger.warning(f"{self.bank_name} request failed, retrying in {backoff}s")
                time.sleep(backoff)

        raise RuntimeError(f"{self.bank_name} API call failed after {retry_count} retries")

    async def fetch_transactions(
        self,
        account_id: str,
        date_from: datetime,
        date_to: datetime,
    ) -> SyncBatch:
        """Fetch transactions for account (to be implemented by subclasses)."""
        raise NotImplementedError

    async def fetch_accounts(self) -> list[dict]:
        """Fetch list of available accounts (to be implemented by subclasses)."""
        raise NotImplementedError


class GarantiPSD2Client(PSD2BankClient):
    """Garanti BBVA PSD2 Open Banking client."""

    bank_name = "Garanti BBVA"
    rate_limit_per_minute = 100

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        sandbox_mode: bool = True,
    ):
        super().__init__(client_id, client_secret, sandbox_mode)

        if sandbox_mode:
            self.auth_url = "https://sandbox-oauth.garantibbva.com.tr/oauth/token"
            self.api_base = "https://sandbox-api.garantibbva.com.tr"
        else:
            self.auth_url = "https://oauth.garantibbva.com.tr/oauth/token"
            self.api_base = "https://api.garantibbva.com.tr"

    async def _get_access_token(self) -> str:
        """Get OAuth2 token from Garanti."""
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                resp = await client.post(
                    self.auth_url,
                    auth=(self.client_id, self.client_secret),
                    data={"grant_type": "client_credentials"},
                )
                resp.raise_for_status()
                data = resp.json()

                self._access_token = data["access_token"]
                expires_in = data.get("expires_in", 3600)
                self._token_expires_at = datetime.now(timezone.utc) + timedelta(
                    seconds=expires_in
                )

                logger.info("Garanti access token obtained")
                return self._access_token
            except httpx.RequestError as e:
                logger.error(f"Garanti token request failed: {e}")
                raise

    async def fetch_accounts(self) -> list[dict]:
        """Fetch list of accounts from Garanti."""
        try:
            data = await self._api_call("GET", "/api/v1/accounts")
            accounts = data.get("data", {}).get("accounts", [])
            logger.info(f"Garanti: fetched {len(accounts)} accounts")
            return accounts
        except Exception as e:
            logger.error(f"Garanti fetch_accounts failed: {e}")
            return []

    async def fetch_transactions(
        self,
        account_id: str,
        date_from: datetime,
        date_to: datetime,
    ) -> SyncBatch:
        """Fetch transactions from Garanti for date range."""
        batch = SyncBatch(
            source_type=SyncSourceType.GARANTI,
            sync_timestamp=datetime.now(timezone.utc),
        )

        try:
            # Garanti endpoint: GET /api/v1/accounts/{accountId}/transactions
            endpoint = f"/api/v1/accounts/{account_id}/transactions"
            params = {
                "from": date_from.date().isoformat(),
                "to": date_to.date().isoformat(),
                "limit": 100,
            }

            page = 1
            total_fetched = 0

            while True:
                params["page"] = page
                data = await self._api_call("GET", endpoint, params=params)

                transactions = data.get("data", {}).get("transactions", [])
                if not transactions:
                    break

                for tx in transactions:
                    try:
                        # Map Garanti fields to SyncTransaction
                        amount_str = tx.get("amount", "0").replace(",", ".")
                        amount_cents = int(float(amount_str) * 100)

                        # Determine transaction type
                        tx_type = TransactionType.INCOME
                        if tx.get("transactionType") in ("DEBIT", "WITHDRAW"):
                            tx_type = TransactionType.EXPENSE

                        transaction = SyncTransaction(
                            date=datetime.fromisoformat(
                                tx["transactionDate"].replace("Z", "+00:00")
                            ),
                            description=tx.get("description", "Garanti Transaction")[:500],
                            amount_cents=amount_cents,
                            tx_type=tx_type,
                            currency=tx.get("currency", "TRY"),
                            vendor=tx.get("counterparty")[:200]
                            if tx.get("counterparty")
                            else None,
                            reference=tx.get("transactionId"),
                            source_type=SyncSourceType.GARANTI,
                            source_id=tx.get("transactionId"),
                            raw_row=str(tx),
                        )
                        batch.transactions.append(transaction)
                        total_fetched += 1

                    except (ValidationError, ValueError) as e:
                        batch.error_count += 1
                        batch.warnings.append(
                            f"Failed to parse Garanti transaction: {e}"
                        )
                        logger.warning(f"Garanti transaction parse error: {e}")

                page += 1
                if len(transactions) < 100:
                    break

            batch.total_processed = total_fetched
            logger.info(f"Garanti: synced {total_fetched} transactions for {account_id}")

        except Exception as e:
            batch.error_count += 1
            batch.warnings.append(f"Garanti sync failed: {e}")
            logger.error(f"Garanti sync error: {e}", exc_info=True)

        return batch


class AkbankPSD2Client(PSD2BankClient):
    """Akbank PSD2 Open Banking client."""

    bank_name = "Akbank"
    rate_limit_per_minute = 100

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        sandbox_mode: bool = True,
    ):
        super().__init__(client_id, client_secret, sandbox_mode)

        if sandbox_mode:
            self.auth_url = "https://sandbox-oauth.akbank.com.tr/oauth/token"
            self.api_base = "https://sandbox-api.akbank.com.tr"
        else:
            self.auth_url = "https://oauth.akbank.com.tr/oauth/token"
            self.api_base = "https://api.akbank.com.tr"

    async def _get_access_token(self) -> str:
        """Get OAuth2 token from Akbank."""
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                resp = await client.post(
                    self.auth_url,
                    auth=(self.client_id, self.client_secret),
                    data={"grant_type": "client_credentials"},
                )
                resp.raise_for_status()
                data = resp.json()

                self._access_token = data["access_token"]
                expires_in = data.get("expires_in", 3600)
                self._token_expires_at = datetime.now(timezone.utc) + timedelta(
                    seconds=expires_in
                )

                logger.info("Akbank access token obtained")
                return self._access_token
            except httpx.RequestError as e:
                logger.error(f"Akbank token request failed: {e}")
                raise

    async def fetch_accounts(self) -> list[dict]:
        """Fetch list of accounts from Akbank."""
        try:
            data = await self._api_call("GET", "/api/v1/accounts")
            accounts = data.get("accounts", [])
            logger.info(f"Akbank: fetched {len(accounts)} accounts")
            return accounts
        except Exception as e:
            logger.error(f"Akbank fetch_accounts failed: {e}")
            return []

    async def fetch_transactions(
        self,
        account_id: str,
        date_from: datetime,
        date_to: datetime,
    ) -> SyncBatch:
        """Fetch transactions from Akbank for date range."""
        batch = SyncBatch(
            source_type=SyncSourceType.AKBANK,
            sync_timestamp=datetime.now(timezone.utc),
        )

        try:
            # Akbank endpoint: GET /api/v1/accounts/{accountId}/transactions
            endpoint = f"/api/v1/accounts/{account_id}/transactions"
            params = {
                "startDate": date_from.date().isoformat(),
                "endDate": date_to.date().isoformat(),
                "pageSize": 100,
            }

            page = 1
            total_fetched = 0

            while True:
                params["pageNumber"] = page
                data = await self._api_call("GET", endpoint, params=params)

                transactions = data.get("transactions", [])
                if not transactions:
                    break

                for tx in transactions:
                    try:
                        # Map Akbank fields to SyncTransaction
                        amount_str = tx.get("amount", "0").replace(",", ".")
                        amount_cents = int(float(amount_str) * 100)

                        # Determine transaction type
                        tx_type = TransactionType.INCOME
                        if tx.get("debitCredit") == "DEBIT":
                            tx_type = TransactionType.EXPENSE

                        transaction = SyncTransaction(
                            date=datetime.fromisoformat(
                                tx["transactionDate"].replace("Z", "+00:00")
                            ),
                            description=tx.get("description", "Akbank Transaction")[:500],
                            amount_cents=amount_cents,
                            tx_type=tx_type,
                            currency=tx.get("currency", "TRY"),
                            vendor=tx.get("counterpartyName")[:200]
                            if tx.get("counterpartyName")
                            else None,
                            reference=tx.get("transactionId"),
                            source_type=SyncSourceType.AKBANK,
                            source_id=tx.get("transactionId"),
                            raw_row=str(tx),
                        )
                        batch.transactions.append(transaction)
                        total_fetched += 1

                    except (ValidationError, ValueError) as e:
                        batch.error_count += 1
                        batch.warnings.append(f"Failed to parse Akbank transaction: {e}")
                        logger.warning(f"Akbank transaction parse error: {e}")

                page += 1
                if len(transactions) < 100:
                    break

            batch.total_processed = total_fetched
            logger.info(f"Akbank: synced {total_fetched} transactions for {account_id}")

        except Exception as e:
            batch.error_count += 1
            batch.warnings.append(f"Akbank sync failed: {e}")
            logger.error(f"Akbank sync error: {e}", exc_info=True)

        return batch

    async def fetch_account_balance(self, account_id: str) -> Optional[int]:
        """Fetch current balance for account (in cents)."""
        try:
            endpoint = f"/api/v1/accounts/{account_id}"
            data = await self._api_call("GET", endpoint)

            balance_str = data.get("balance", "0").replace(",", ".")
            balance_cents = int(float(balance_str) * 100)
            logger.info(f"Akbank balance for {account_id}: {balance_cents / 100:.2f} TRY")
            return balance_cents

        except Exception as e:
            logger.error(f"Akbank balance fetch failed: {e}")
            return None
