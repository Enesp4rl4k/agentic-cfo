"""
Paraşüt OAuth2 API client — cloud-native accounting platform.

Handles:
  - OAuth2 token refresh
  - Transaction/invoice API calls
  - Error handling + exponential backoff retry
  - Rate limiting (Paraşüt: 100 req/min)
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

# Paraşüt API endpoints
PARASUT_API_BASE = "https://api.parasut.com/v4"
PARASUT_OAUTH_TOKEN = "https://api.parasut.com/oauth/token"


class ParasutClient:
    """OAuth2 client for Paraşüt accounting API."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        company_id: str,
    ):
        """
        Initialize Paraşüt client.

        Args:
            client_id: OAuth2 client ID
            client_secret: OAuth2 client secret
            refresh_token: Stored refresh token
            company_id: Paraşüt company ID (numeric)
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.company_id = company_id
        
        self._access_token: Optional[str] = None
        self._token_expires_at: Optional[datetime] = None
        self._rate_limit_reset: datetime = datetime.now(timezone.utc)

    async def _refresh_access_token(self) -> str:
        """Refresh OAuth2 access token."""
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                resp = await client.post(
                    PARASUT_OAUTH_TOKEN,
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": self.refresh_token,
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                
                self._access_token = data["access_token"]
                expires_in = data.get("expires_in", 3600)
                self._token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
                
                logger.info("Paraşüt access token refreshed")
                return self._access_token
            except httpx.RequestError as e:
                logger.error(f"Paraşüt token refresh failed: {e}")
                raise

    async def _ensure_token(self) -> str:
        """Ensure valid access token, refresh if needed."""
        if (
            self._access_token
            and self._token_expires_at
            and datetime.now(timezone.utc) < self._token_expires_at - timedelta(minutes=5)
        ):
            return self._access_token
        
        return await self._refresh_access_token()

    async def _api_call(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict] = None,
        json_data: Optional[dict] = None,
        retry_count: int = 3,
    ) -> dict:
        """
        Make API call with rate limit + retry logic.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint path (without base URL)
            params: Query parameters
            json_data: Request body
            retry_count: Max retries on rate limit

        Returns:
            Response JSON
        """
        # Respect rate limit
        now = datetime.now(timezone.utc)
        if now < self._rate_limit_reset:
            sleep_time = (self._rate_limit_reset - now).total_seconds()
            logger.warning(f"Rate limit: sleeping {sleep_time:.1f}s")
            time.sleep(sleep_time)

        token = await self._ensure_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        url = f"{PARASUT_API_BASE}/{endpoint}"
        
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

                    # Check rate limit headers
                    if "X-RateLimit-Reset" in resp.headers:
                        reset_epoch = int(resp.headers["X-RateLimit-Reset"])
                        self._rate_limit_reset = datetime.fromtimestamp(
                            reset_epoch, tz=timezone.utc
                        )

                    if resp.status_code == 429:
                        # Rate limited — exponential backoff
                        backoff = 2 ** attempt
                        logger.warning(
                            f"Rate limited (attempt {attempt + 1}), backing off {backoff}s"
                        )
                        time.sleep(backoff)
                        continue

                    resp.raise_for_status()
                    return resp.json()

            except httpx.RequestError as e:
                if attempt == retry_count - 1:
                    logger.error(f"API call failed after {retry_count} retries: {e}")
                    raise
                backoff = 2 ** attempt
                logger.warning(f"Request failed, retrying in {backoff}s: {e}")
                time.sleep(backoff)

        raise RuntimeError(f"API call failed after {retry_count} retries")

    async def sync_transactions(
        self,
        date_from: datetime,
        date_to: datetime,
    ) -> SyncBatch:
        """
        Fetch transactions from Paraşüt for date range.

        Calls GET /transactions with date filters.
        """
        batch = SyncBatch(
            source_type=SyncSourceType.PARASUT,
            sync_timestamp=datetime.now(timezone.utc),
        )

        try:
            # Fetch transactions
            params = {
                "filter[date_gte]": date_from.date().isoformat(),
                "filter[date_lte]": date_to.date().isoformat(),
                "page[limit]": 100,
            }

            page = 1
            total_fetched = 0

            while True:
                params["page[number]"] = page
                data = await self._api_call("GET", "transactions", params=params)

                transactions = data.get("data", [])
                if not transactions:
                    break

                for tx in transactions:
                    try:
                        # Map Paraşüt fields to SyncTransaction
                        amount_cents = int(float(tx.get("amount", 0)) * 100)
                        tx_type_str = tx.get("transaction_type", "expense").lower()
                        tx_type = TransactionType.INCOME if "income" in tx_type_str else TransactionType.EXPENSE

                        transaction = SyncTransaction(
                            date=datetime.fromisoformat(tx["date"]),
                            description=tx.get("description", "Paraşüt Transaction")[:500],
                            amount_cents=amount_cents,
                            tx_type=tx_type,
                            currency="TRY",
                            vendor=tx.get("contact_name")[:200] if tx.get("contact_name") else None,
                            reference=tx.get("id"),
                            source_type=SyncSourceType.PARASUT,
                            source_id=tx.get("id"),
                            raw_row=str(tx),
                        )
                        batch.transactions.append(transaction)
                        total_fetched += 1

                    except (ValidationError, ValueError) as e:
                        batch.error_count += 1
                        batch.warnings.append(f"Failed to parse transaction {tx.get('id')}: {e}")
                        logger.warning(f"Paraşüt transaction parse error: {e}")

                page += 1
                if len(transactions) < 100:
                    break

            batch.total_processed = total_fetched
            logger.info(f"Paraşüt: synced {total_fetched} transactions")

        except Exception as e:
            batch.error_count += 1
            batch.warnings.append(f"Paraşüt sync failed: {e}")
            logger.error(f"Paraşüt sync error: {e}", exc_info=True)

        return batch

    async def sync_invoices(
        self,
        date_from: datetime,
        date_to: datetime,
    ) -> SyncBatch:
        """
        Fetch invoices (sales + purchases) from Paraşüt.

        Maps to transactions for revenue/expense tracking.
        """
        batch = SyncBatch(
            source_type=SyncSourceType.PARASUT,
            sync_timestamp=datetime.now(timezone.utc),
        )

        try:
            total_fetched = 0

            # Sales invoices (income)
            params = {
                "filter[issued_date_gte]": date_from.date().isoformat(),
                "filter[issued_date_lte]": date_to.date().isoformat(),
                "page[limit]": 100,
            }

            page = 1
            while True:
                params["page[number]"] = page
                data = await self._api_call("GET", "sales_invoices", params=params)
                invoices = data.get("data", [])
                if not invoices:
                    break

                for inv in invoices:
                    amount_cents = int(float(inv.get("total_in_currency", 0)) * 100)
                    if amount_cents > 0:
                        transaction = SyncTransaction(
                            date=datetime.fromisoformat(inv["issued_date"]),
                            description=f"Sales Invoice {inv.get('invoice_number')}",
                            amount_cents=amount_cents,
                            tx_type=TransactionType.INCOME,
                            currency=inv.get("currency_code", "TRY"),
                            vendor=inv.get("customer_name")[:200] if inv.get("customer_name") else None,
                            reference=inv.get("id"),
                            source_type=SyncSourceType.PARASUT,
                            source_id=inv.get("id"),
                            raw_row=str(inv),
                        )
                        batch.transactions.append(transaction)
                        total_fetched += 1

                page += 1
                if len(invoices) < 100:
                    break

            # Purchase invoices (expense)
            page = 1
            while True:
                params["page[number]"] = page
                data = await self._api_call("GET", "purchase_invoices", params=params)
                invoices = data.get("data", [])
                if not invoices:
                    break

                for inv in invoices:
                    amount_cents = int(float(inv.get("total_in_currency", 0)) * 100)
                    if amount_cents > 0:
                        transaction = SyncTransaction(
                            date=datetime.fromisoformat(inv["issued_date"]),
                            description=f"Purchase Invoice {inv.get('invoice_number')}",
                            amount_cents=amount_cents,
                            tx_type=TransactionType.EXPENSE,
                            currency=inv.get("currency_code", "TRY"),
                            vendor=inv.get("supplier_name")[:200] if inv.get("supplier_name") else None,
                            reference=inv.get("id"),
                            source_type=SyncSourceType.PARASUT,
                            source_id=inv.get("id"),
                            raw_row=str(inv),
                        )
                        batch.transactions.append(transaction)
                        total_fetched += 1

                page += 1
                if len(invoices) < 100:
                    break

            batch.total_processed = total_fetched
            logger.info(f"Paraşüt invoices: synced {total_fetched} items")

        except Exception as e:
            batch.error_count += 1
            batch.warnings.append(f"Paraşüt invoice sync failed: {e}")
            logger.error(f"Paraşüt invoice sync error: {e}", exc_info=True)

        return batch

    def compute_batch_hash(self, batch: SyncBatch) -> str:
        """Compute SHA256 hash of batch for audit trail."""
        batch_str = "\n".join(
            f"{t.date.isoformat()}|{t.source_id}|{t.amount_cents}"
            for t in sorted(batch.transactions, key=lambda x: (x.date, x.source_id or ""))
        )
        return hashlib.sha256(batch_str.encode()).hexdigest()
