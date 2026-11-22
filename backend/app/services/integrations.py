"""
Harici Entegrasyon Servisleri — Alan 4

INT-2: Open Banking (BKM Express / BDDK)
INT-4: E-ticaret kanalları (Shopify, Trendyol)
INT-5: Google Sheets iki yönlü sync
INT-6: (removed) outbound Slack/Teams/webhook/e-mail now go only through app.services.outbox

Her connector:
  - Async httpx client
  - Hata toleransı (graceful degradation)
  - Redis cache (API rate limit koruması)
  - Standart SyncBatch çıktısı (CFO pipeline'a direkt beslenir)
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime
from typing import Any
from urllib.parse import urlencode

import httpx

from app.core import outbound
from app.core.dates import istanbul
from app.services.ingest.feed import (
    Feed,
    FeedFailed,
    FeedResult,
    direction_from_sign,
    first,
    item_is_blank,
    read_money,
)

logger = logging.getLogger(__name__)


def _failed(feed: Feed, what: str, exc: Exception) -> FeedResult:
    """A fetch that did not work is a failed result with the reason: the status or the kind of error, no body."""
    reason = str(exc) if isinstance(exc, FeedFailed) else type(exc).__name__
    return feed.fail(f"{what}: {reason}")


# ═══════════════════════════════════════════════════════════════════════════════
# INT-2: Open Banking — Türkiye
# ═══════════════════════════════════════════════════════════════════════════════

class TurkiyeOpenBankingClient:
    """
    Türkiye Open Banking (OBP) connector.

    BDDK düzenlemesiyle 2020'den beri Türkiye bankaları PSD2-uyumlu API sunar.
    BKM Express ve ÖDEAL platformları üzerinden erişilebilir.

    Desteklenen bankalar (sandbox):
      - Akbank     (developer.akbank.com)
      - Garanti    (developer.garantibbva.com.tr)
      - İş Bankası (apideveloper.isbank.com.tr)
      - YapıKredi  (developer.yapikredi.com.tr)

    Bu client sandbox ortamını hedefler.
    Production için her bankadan ayrı OAuth2 client credentials gerekir.
    """

    SANDBOX_URLS = {
        "akbank":    "https://apisandbox.akbank.com/api/v1",
        "garanti":   "https://api.garanti.com.tr/sandbox/v1",
        "isbank":    "https://sandbox.isbank.com.tr/openbanking/v1",
        "yapikredi": "https://api.yapikredi.com.tr/sandbox/v1",
    }

    def __init__(self, bank: str, client_id: str, client_secret: str, sandbox: bool = True) -> None:
        self.bank          = bank
        self.client_id     = client_id
        self.client_secret = client_secret
        self.sandbox       = sandbox
        self._token:     str | None = None
        self._token_exp: float      = 0.0

    async def _get_token(self) -> str:
        """OAuth2 client credentials token al."""
        import time
        if self._token and time.time() < self._token_exp - 60:
            return self._token

        base = self.SANDBOX_URLS.get(self.bank, self.SANDBOX_URLS["akbank"])
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{base}/oauth/token",
                data={
                    "grant_type":    "client_credentials",
                    "client_id":     self.client_id,
                    "client_secret": self.client_secret,
                    "scope":         "accounts transactions",
                },
            )
            if resp.status_code != 200:
                raise RuntimeError(f"Open Banking token hatası: {resp.status_code}")
            data          = resp.json()
            self._token   = data["access_token"]
            self._token_exp = time.time() + data.get("expires_in", 3600)
            return self._token

    async def list_accounts(self) -> list[dict]:
        """Banka hesaplarını listele. A refusal raises: an outage is not "no accounts"."""
        token = await self._get_token()
        base  = self.SANDBOX_URLS.get(self.bank, self.SANDBOX_URLS["akbank"])
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{base}/accounts",
                headers={"Authorization": f"Bearer {token}"},
            )
            if resp.status_code != 200:
                raise RuntimeError(f"Open Banking hesap listesi hatası: {resp.status_code}")
            return resp.json().get("accounts", [])

    async def get_transactions(self, account_id: str, from_date: str, to_date: str) -> FeedResult:
        """Hesap hareketlerini çek → one row per movement; a failed fetch is `failed`, never an empty list."""
        feed = Feed(f"{self.bank}_open_banking")
        try:
            token = await self._get_token()
            base  = self.SANDBOX_URLS.get(self.bank, self.SANDBOX_URLS["akbank"])
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    f"{base}/accounts/{account_id}/transactions",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"fromDate": from_date, "toDate": to_date},
                )
            if resp.status_code != 200:
                raise FeedFailed(f"banka {resp.status_code} yanıtı verdi")
            payload = resp.json()
            raw_txs = payload.get("transactions") if isinstance(payload, dict) else None
            if not isinstance(raw_txs, list):
                raise FeedFailed("yanıtta transactions listesi yok (beklenmeyen biçim)")
        except (httpx.HTTPError, RuntimeError, ValueError, FeedFailed) as exc:
            return _failed(feed, "hesap hareketleri alınamadı", exc)
        for tx in feed.each(raw_txs):
            self._add(feed, tx)
        if isinstance(payload.get("_links"), dict) and payload["_links"].get("next"):
            feed.partial = "sonraki sayfa çekilmedi (bu istemci sayfalama yapmıyor)"
        return feed.result()

    def _add(self, feed: Feed, tx: Any) -> None:
        """One movement as a row. The sign gives the direction; no amount means no sign, no value, and a held row."""
        if item_is_blank(tx):
            feed.blank()
            return
        amount_obj = first(tx, "amount")
        raw_amount = first(amount_obj, "amount")
        date = first(tx, "bookingDate", "valueDate")
        currency = first(amount_obj, "currency")
        feed.add(
            amount=raw_amount, direction=direction_from_sign(read_money(raw_amount)), date=date, currency=currency,
            description=str(first(tx, "transactionText", "description") or ""), reference=first(tx, "transactionId"),
            evidence={"amount": raw_amount, "currency": currency, "bookingDate": date,
                      "transactionId": first(tx, "transactionId")},
            bank=self.bank,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# INT-4: E-ticaret kanalları
# ═══════════════════════════════════════════════════════════════════════════════

_SHOP_MAX_BYTES = 8 * 1024 * 1024


class ShopifyConnector:
    """Shopify Admin API — sipariş ve ödeme reconciliation."""

    # The host comes from request credentials: only `<shop>.myshopify.com`, label checked here,
    # and the request goes through the SSRF guard (app/core/outbound.py).
    _SHOP_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,58}[a-z0-9])?$")

    def __init__(self, shop_domain: str, access_token: str) -> None:
        label = shop_domain.strip().lower().removesuffix(".myshopify.com")
        if not self._SHOP_LABEL.match(label):
            raise ValueError("shop_domain <magaza>.myshopify.com biçiminde olmalı")
        self.base  = f"https://{label}.myshopify.com/admin/api/2024-01"
        self.token = access_token

    async def get_orders(self, from_date: str, to_date: str) -> FeedResult:
        feed = Feed("shopify")
        params = {
            "created_at_min": from_date,
            "created_at_max": to_date,
            "status":         "any",
            "limit":          250,
        }
        try:
            resp = await outbound.request(
                "GET", f"{self.base}/orders.json?{urlencode(params)}",
                headers={"X-Shopify-Access-Token": self.token}, max_bytes=_SHOP_MAX_BYTES, timeout=30,
            )
            if resp.status_code != 200:
                raise FeedFailed(f"Shopify {resp.status_code} yanıtı verdi")
            payload = json.loads(resp.body or b"")
            orders = payload.get("orders") if isinstance(payload, dict) else None
            if not isinstance(orders, list):
                raise FeedFailed("yanıtta orders listesi yok (beklenmeyen biçim)")
        except (httpx.HTTPError, ValueError, FeedFailed, outbound.OutboundBlocked) as exc:
            logger.warning("Shopify orders failed: %s", type(exc).__name__)
            return _failed(feed, "Shopify siparişleri alınamadı", exc)
        for o in feed.each(orders):
            self._add(feed, o)
        if 'rel="next"' in resp.headers.get("link", ""):
            feed.partial = "Shopify'ın sonraki sayfası çekilmedi (en fazla 250 sipariş okunur)"
        return feed.result()

    @staticmethod
    def _add(feed: Feed, o: Any) -> None:
        if item_is_blank(o):
            feed.blank()
            return
        total = first(o, "total_price")
        date = str(first(o, "processed_at", "created_at") or "")[:10]
        feed.add(
            amount=total, direction="income", date=date, currency=first(o, "currency"),
            description=f"Shopify Sipariş #{first(o, 'order_number') or first(o, 'id') or ''}",
            reference=str(first(o, "id") or ""),
            evidence={"total_price": total, "created_at": first(o, "processed_at", "created_at"),
                      "order": first(o, "order_number")},
            channel="shopify", customer_email=o.get("email") if isinstance(o, dict) else None,
            order_id=str(first(o, "id") or ""),
        )


class TrendyolConnector:
    """Trendyol Supplier API — satıcı siparişleri."""

    def __init__(self, supplier_id: str, api_key: str, api_secret: str) -> None:
        self.base        = "https://api.trendyol.com/sapigw"
        if not supplier_id.isdigit() or len(supplier_id) > 20:  # a path segment of a fixed host
            raise ValueError("supplier_id sayısal olmalı")
        self.supplier_id = supplier_id
        self.auth        = httpx.BasicAuth(api_key, api_secret)

    async def get_orders(self, from_date: str, to_date: str) -> FeedResult:
        feed = Feed("trendyol")
        # Trendyol uses Unix millisecond timestamps
        from_ts = int(datetime.fromisoformat(from_date).timestamp() * 1000)
        to_ts   = int(datetime.fromisoformat(to_date).timestamp() * 1000)
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    f"{self.base}/suppliers/{self.supplier_id}/orders",
                    auth=self.auth,
                    params={"startDate": from_ts, "endDate": to_ts, "size": 200},
                    headers={"User-Agent": "AgenticCFO/1.0"},
                )
            if resp.status_code != 200:
                raise FeedFailed(f"Trendyol {resp.status_code} yanıtı verdi")
            payload = resp.json()
            content = payload.get("content") if isinstance(payload, dict) else None
            if not isinstance(content, list):
                raise FeedFailed("yanıtta content listesi yok (beklenmeyen biçim)")
        except (httpx.HTTPError, ValueError, FeedFailed) as exc:
            logger.warning("Trendyol orders failed: %s", type(exc).__name__)
            return _failed(feed, "Trendyol siparişleri alınamadı", exc)
        for o in feed.each(content):
            self._add(feed, o)
        pages = payload.get("totalPages")
        if isinstance(pages, int) and pages > 1:
            feed.partial = f"Trendyol {pages} sayfa döndürdü; yalnızca ilk sayfa çekildi"
        return feed.result()

    @staticmethod
    def _add(feed: Feed, o: Any) -> None:
        """One row per order line; an order with no lines is ONE row (its own total), never nothing."""
        if item_is_blank(o):
            feed.blank()
            return
        stamp = first(o, "orderDate")
        date: Any = None
        if isinstance(stamp, (int, float)) and not isinstance(stamp, bool) and stamp > 0:
            date = datetime.fromtimestamp(stamp / 1000, tz=istanbul()).strftime("%Y-%m-%d")
        lines = o.get("lines") if isinstance(o, dict) else None
        if not isinstance(lines, list) or not lines:
            lines = [{"amount": first(o, "grossAmount", "totalPrice"), "productName": ""}]
        for line in lines:
            amount = first(line, "amount")
            feed.add(
                amount=amount, direction="income", date=date,
                currency=first(line, "currencyCode") or first(o, "currencyCode"),
                description=f"Trendyol Sipariş #{first(o, 'orderNumber') or ''} — {first(line, 'productName') or ''}",
                reference=str(first(o, "id") or ""),
                evidence={"amount": amount, "orderDate": stamp, "orderNumber": first(o, "orderNumber")},
                channel="trendyol", order_id=str(first(o, "id") or ""),
            )


# ═══════════════════════════════════════════════════════════════════════════════
# INT-5: Google Sheets Sync
# ═══════════════════════════════════════════════════════════════════════════════

class GoogleSheetsConnector:
    """
    Google Sheets bidirectional sync.

    Read: Import financial data from a spreadsheet
    Write: Push CFO analysis results to a spreadsheet

    Auth: OAuth2 service account (JSON key file in .env as base64)
    """

    def __init__(self, service_account_json: str) -> None:
        self._sa_json = service_account_json

    def _build_credentials(self):
        """Build Google API credentials from service account JSON."""
        try:
            import json as _json

            from google.oauth2.service_account import Credentials
            info   = _json.loads(self._sa_json)
            scopes = ["https://www.googleapis.com/auth/spreadsheets"]
            return Credentials.from_service_account_info(info, scopes=scopes)
        except ImportError:
            raise RuntimeError(
                "google-auth not installed. "
                "Add 'google-auth google-auth-httplib2 google-api-python-client' to requirements."
            )

    async def read_sheet(
        self,
        spreadsheet_id: str,
        range_name:     str = "Sheet1!A1:Z1000",
    ) -> list[list[Any]]:
        """Read data from a Google Sheet range."""
        def _read() -> list[list[Any]]:
            from googleapiclient.discovery import build
            service = build("sheets", "v4", credentials=self._build_credentials())
            result = service.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id,
                range=range_name,
            ).execute()
            return result.get("values", [])

        # The Google client is synchronous HTTP; on the loop it held every request.
        return await asyncio.to_thread(_read)

    async def write_sheet(
        self,
        spreadsheet_id: str,
        range_name:     str,
        values:         list[list[Any]],
    ) -> dict:
        """Write data to a Google Sheet range."""
        def _write() -> dict:
            from googleapiclient.discovery import build
            service = build("sheets", "v4", credentials=self._build_credentials())
            return service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=range_name,
                valueInputOption="RAW",
                body={"values": values},
            ).execute()

        return await asyncio.to_thread(_write)

    async def export_cfo_results(
        self,
        spreadsheet_id: str,
        cfo_result:     dict,
    ) -> None:
        """Export CFO pipeline results to a structured Google Sheet."""
        pnl = cfo_result.get("pnl", {})
        rows = [
            ["Metrik", "Değer", "Güncelleme"],
            [f"Gelir ({pnl.get('currency')})" if pnl.get("currency") else "Gelir", pnl.get("revenue", 0) / 100, datetime.now().strftime("%Y-%m-%d %H:%M")],
            ["Brüt Marj %", round((pnl.get("gross_margin", 0)) * 100, 1), ""],
            ["Net Marj %",  round((pnl.get("net_margin", 0)) * 100, 1),  ""],
        ]
        await self.write_sheet(spreadsheet_id, "CFO!A1", rows)
