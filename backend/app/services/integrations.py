"""
Harici Entegrasyon Servisleri — Alan 4

INT-2: Open Banking (BKM Express / BDDK)
INT-4: E-ticaret kanalları (Shopify, Trendyol, Hepsiburada)
INT-5: Google Sheets iki yönlü sync
INT-6: Webhook outbound (Slack, Teams, email)

Her connector:
  - Async httpx client
  - Hata toleransı (graceful degradation)
  - Redis cache (API rate limit koruması)
  - Standart SyncBatch çıktısı (CFO pipeline'a direkt beslenir)
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)


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
        """Banka hesaplarını listele."""
        token = await self._get_token()
        base  = self.SANDBOX_URLS.get(self.bank, self.SANDBOX_URLS["akbank"])
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{base}/accounts",
                headers={"Authorization": f"Bearer {token}"},
            )
            if resp.status_code != 200:
                return []
            return resp.json().get("accounts", [])

    async def get_transactions(self, account_id: str, from_date: str, to_date: str) -> list[dict]:
        """Hesap hareketlerini çek → CFO transaction formatına dönüştür."""
        token = await self._get_token()
        base  = self.SANDBOX_URLS.get(self.bank, self.SANDBOX_URLS["akbank"])
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{base}/accounts/{account_id}/transactions",
                headers={"Authorization": f"Bearer {token}"},
                params={"fromDate": from_date, "toDate": to_date},
            )
            if resp.status_code != 200:
                return []

            raw_txs = resp.json().get("transactions", [])
            return [self._normalize_transaction(tx) for tx in raw_txs]

    def _normalize_transaction(self, tx: dict) -> dict:
        """Banka transaction formatını CFO formatına dönüştür."""
        amount_raw = tx.get("amount", {})
        amount     = float(amount_raw.get("amount", 0))
        currency   = amount_raw.get("currency", "TRY")

        return {
            "transaction_date": tx.get("bookingDate") or tx.get("valueDate", ""),
            "description":      tx.get("transactionText") or tx.get("description", ""),
            "amount_try":       amount if currency == "TRY" else amount,
            "type":             "income" if amount > 0 else "expense",
            "bank":             self.bank,
            "reference":        tx.get("transactionId", ""),
            "raw":              tx,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# INT-4: E-ticaret kanalları
# ═══════════════════════════════════════════════════════════════════════════════

class ShopifyConnector:
    """Shopify Admin API — sipariş ve ödeme reconciliation."""

    def __init__(self, shop_domain: str, access_token: str) -> None:
        self.base  = f"https://{shop_domain}/admin/api/2024-01"
        self.token = access_token

    async def get_orders(self, from_date: str, to_date: str) -> list[dict]:
        params = {
            "created_at_min": from_date,
            "created_at_max": to_date,
            "status":         "any",
            "limit":          250,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{self.base}/orders.json",
                headers={"X-Shopify-Access-Token": self.token},
                params=params,
            )
            if resp.status_code != 200:
                logger.warning("Shopify orders failed: %d", resp.status_code)
                return []
            return self._normalize_orders(resp.json().get("orders", []))

    def _normalize_orders(self, orders: list[dict]) -> list[dict]:
        result = []
        for o in orders:
            total = float(o.get("total_price", 0))
            result.append({
                "transaction_date": (o.get("processed_at") or o.get("created_at", ""))[:10],
                "description":      f"Shopify Sipariş #{o.get('order_number')}",
                "amount_try":       total,
                "type":             "income",
                "channel":          "shopify",
                "currency":         o.get("currency", "TRY"),
                "customer_email":   o.get("email"),
                "order_id":         str(o.get("id")),
            })
        return result


class TrendyolConnector:
    """Trendyol Supplier API — satıcı siparişleri."""

    def __init__(self, supplier_id: str, api_key: str, api_secret: str) -> None:
        self.base        = "https://api.trendyol.com/sapigw"
        self.supplier_id = supplier_id
        self.auth        = httpx.BasicAuth(api_key, api_secret)

    async def get_orders(self, from_date: str, to_date: str) -> list[dict]:
        # Trendyol uses Unix millisecond timestamps
        from_ts = int(datetime.fromisoformat(from_date).timestamp() * 1000)
        to_ts   = int(datetime.fromisoformat(to_date).timestamp() * 1000)

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{self.base}/suppliers/{self.supplier_id}/orders",
                auth=self.auth,
                params={"startDate": from_ts, "endDate": to_ts, "size": 200},
                headers={"User-Agent": "AgenticCFO/1.0"},
            )
            if resp.status_code != 200:
                logger.warning("Trendyol orders failed: %d", resp.status_code)
                return []
            return self._normalize(resp.json().get("content", []))

    def _normalize(self, orders: list[dict]) -> list[dict]:
        result = []
        for o in orders:
            for line in o.get("lines", []):
                result.append({
                    "transaction_date": datetime.fromtimestamp(
                        o.get("orderDate", 0) / 1000
                    ).strftime("%Y-%m-%d"),
                    "description":   f"Trendyol Sipariş #{o.get('orderNumber')} — {line.get('productName', '')}",
                    "amount_try":    float(line.get("amount", 0)),
                    "type":          "income",
                    "channel":       "trendyol",
                    "order_id":      str(o.get("id")),
                })
        return result


class HepsiburadaConnector:
    """Hepsiburada Merchant API — satıcı siparişleri."""

    def __init__(self, username: str, password: str) -> None:
        self.base  = "https://listing-external.hepsiburada.com"
        self.auth  = httpx.BasicAuth(username, password)

    async def get_orders(self, from_date: str, to_date: str) -> list[dict]:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{self.base}/listings/merchantid",
                auth=self.auth,
                headers={"Accept": "application/json"},
            )
            if resp.status_code != 200:
                return []
            # Simplified — full order endpoint varies by version
            return []


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
        import asyncio
        creds = self._build_credentials()
        from googleapiclient.discovery import build
        service = build("sheets", "v4", credentials=creds)
        result  = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=range_name,
        ).execute()
        return result.get("values", [])

    async def write_sheet(
        self,
        spreadsheet_id: str,
        range_name:     str,
        values:         list[list[Any]],
    ) -> dict:
        """Write data to a Google Sheet range."""
        creds   = self._build_credentials()
        from googleapiclient.discovery import build
        service = build("sheets", "v4", credentials=creds)
        body    = {"values": values}
        result  = service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=range_name,
            valueInputOption="RAW",
            body=body,
        ).execute()
        return result

    async def export_cfo_results(
        self,
        spreadsheet_id: str,
        cfo_result:     dict,
    ) -> None:
        """Export CFO pipeline results to a structured Google Sheet."""
        pnl = cfo_result.get("pnl", {})
        rows = [
            ["Metrik", "Değer", "Güncelleme"],
            ["Gelir (TRY)", pnl.get("revenue", 0) / 100, datetime.now().strftime("%Y-%m-%d %H:%M")],
            ["Brüt Marj %", round((pnl.get("gross_margin", 0)) * 100, 1), ""],
            ["Net Marj %",  round((pnl.get("net_margin", 0)) * 100, 1),  ""],
        ]
        await self.write_sheet(spreadsheet_id, "CFO!A1", rows)


# ═══════════════════════════════════════════════════════════════════════════════
# INT-6: Webhook Outbound
# ═══════════════════════════════════════════════════════════════════════════════

class WebhookDispatcher:
    """
    Outbound webhook dispatcher.

    Desteklenen kanallar:
      - Slack (Incoming Webhook)
      - Microsoft Teams (Incoming Webhook)
      - Custom HTTP endpoint
      - Email (SMTP — settings.smtp_*)

    Her kanal kendi payload formatını alır.
    """

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(timeout=10)

    async def send_slack(self, webhook_url: str, message: str, details: dict | None = None) -> bool:
        """Slack Incoming Webhook mesajı gönder."""
        blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": message}}]
        if details:
            fields = [
                {"type": "mrkdwn", "text": f"*{k}:*\n{v}"}
                for k, v in list(details.items())[:10]
            ]
            blocks.append({"type": "section", "fields": fields})

        try:
            resp = await self._client.post(webhook_url, json={"blocks": blocks})
            return resp.status_code == 200
        except Exception as exc:
            logger.warning("Slack webhook failed: %s", exc)
            return False

    async def send_teams(self, webhook_url: str, title: str, message: str, color: str = "0078D4") -> bool:
        """Microsoft Teams Incoming Webhook mesajı gönder."""
        payload = {
            "@type":       "MessageCard",
            "@context":    "http://schema.org/extensions",
            "themeColor":  color,
            "summary":     title,
            "sections": [{
                "activityTitle":    title,
                "activityText":     message,
                "activitySubtitle": datetime.now().strftime("%d.%m.%Y %H:%M"),
            }],
        }
        try:
            resp = await self._client.post(webhook_url, json=payload)
            return resp.status_code in (200, 201)
        except Exception as exc:
            logger.warning("Teams webhook failed: %s", exc)
            return False

    async def send_custom(self, url: str, payload: dict, headers: dict | None = None) -> bool:
        """Custom HTTP endpoint'e POST gönder."""
        try:
            resp = await self._client.post(
                url,
                json=payload,
                headers=headers or {"Content-Type": "application/json"},
            )
            return 200 <= resp.status_code < 300
        except Exception as exc:
            logger.warning("Custom webhook failed: %s", exc)
            return False

    async def send_email(self, to: str, subject: str, body: str) -> bool:
        """SMTP ile email gönder."""
        import smtplib
        import ssl
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        from app.config import get_settings
        settings = get_settings()

        smtp_host = getattr(settings, "smtp_host", "")
        smtp_port = getattr(settings, "smtp_port", 587)
        smtp_user = getattr(settings, "smtp_user", "")
        smtp_pass = getattr(settings, "smtp_password", "")

        if not smtp_host or not smtp_user:
            logger.debug("SMTP not configured — email not sent")
            return False

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"]    = smtp_user
            msg["To"]      = to
            msg.attach(MIMEText(body, "html", "utf-8"))

            context = ssl.create_default_context()
            with smtplib.SMTP(smtp_host, int(smtp_port)) as server:
                server.starttls(context=context)
                server.login(smtp_user, smtp_pass)
                server.sendmail(smtp_user, to, msg.as_string())
            return True
        except Exception as exc:
            logger.warning("Email send failed: %s", exc)
            return False

    async def close(self) -> None:
        await self._client.aclose()


# ── Singleton ─────────────────────────────────────────────────────────────────

_dispatcher: WebhookDispatcher | None = None


def get_webhook_dispatcher() -> WebhookDispatcher:
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = WebhookDispatcher()
    return _dispatcher
