"""
Parasut ERP Connector

Parasut OAuth2 API ile entegrasyon yonetimi.
Mevcut ParasutClient (data_sync/accounting/parasut.py) uzerine
DB kayit, token yenileme ve CFO pipeline besleme katmani ekler.

Akis:
  1. Kullanici /erp/parasut/connect'e client_id + client_secret girer
  2. OAuth2 redirect URL olusturulur
  3. Callback gelince token kaydedilir (Fernet sifreli)
  4. Sync tetiklendiginde token yenilenir, islemler cekilir
  5. Islemler CFO pipeline'a beslenir

Not: Parasut API'de OAuth2 diger uygulamalara acik.
Kullanicinin Parasut'ta uygulama olusturmasi gerekir.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# Parasut OAuth endpoints
PARASUT_OAUTH_BASE    = "https://api.parasut.com/oauth"
PARASUT_API_BASE      = "https://api.parasut.com/v4"
PARASUT_AUTH_URL      = f"{PARASUT_OAUTH_BASE}/authorize"
PARASUT_TOKEN_URL     = f"{PARASUT_OAUTH_BASE}/token"

PARASUT_SCOPES = [
    "read:sales_invoices",
    "read:purchase_bills",
    "read:transactions",
    "read:bank_fees",
    "read:accounts",
]


def _encrypt(plaintext: str) -> str:
    """Fernet ile sifrele."""
    try:
        import os

        from cryptography.fernet import Fernet
        key = os.environ.get("ENCRYPTION_KEY", "").encode()
        if not key or len(key) < 32:
            # Fernet key gerektirir; yoksa base64 placeholder
            import base64
            return base64.b64encode(plaintext.encode()).decode()
        f = Fernet(key[:44])  # Fernet 44-byte URL-safe base64 key
        return f.encrypt(plaintext.encode()).decode()
    except Exception:
        import base64
        return base64.b64encode(plaintext.encode()).decode()


def _decrypt(ciphertext: str) -> str:
    """Fernet ile coz."""
    try:
        import os

        from cryptography.fernet import Fernet
        key = os.environ.get("ENCRYPTION_KEY", "").encode()
        if not key or len(key) < 32:
            import base64
            return base64.b64decode(ciphertext.encode()).decode()
        f = Fernet(key[:44])
        return f.decrypt(ciphertext.encode()).decode()
    except Exception:
        try:
            import base64
            return base64.b64decode(ciphertext.encode()).decode()
        except Exception:
            return ciphertext


class ParasutConnector:
    """
    Parasut ERP entegrasyon yoneticisi.

    Kullanim:
        connector = ParasutConnector(db)
        auth_url = await connector.get_auth_url(org_id, client_id, client_secret, redirect_uri)
        # Kullanici auth_url'e gider, callback gelir:
        integration = await connector.handle_callback(org_id, code, state)
        # Sync:
        result = await connector.sync(integration_id)
    """

    def __init__(self, db: Any) -> None:
        self.db = db

    async def get_auth_url(
        self,
        org_id:        str,
        client_id:     str,
        client_secret: str,
        redirect_uri:  str,
        company_id:    str,
    ) -> dict[str, Any]:
        """
        OAuth2 authorization URL olustur.
        Kullaniciyi bu URL'e yonlendir.
        """
        from sqlalchemy import select

        from app.models.erp_integration import ERPIntegration

        # Mevcut entegrasyon var mi kontrol et
        stmt = (
            select(ERPIntegration)
            .where(ERPIntegration.org_id == org_id, ERPIntegration.provider == "parasut")
        )
        existing = (await self.db.execute(stmt)).scalar_one_or_none()

        # State olarak integration_id kullan (callback icin)
        state = str(uuid.uuid4())

        # Credential'lari sifreli kaydet (henuz aktif degil)
        config = {
            "client_id":     client_id,
            "client_secret": client_secret,
            "redirect_uri":  redirect_uri,
            "company_id":    company_id,
            "oauth_state":   state,
        }

        if existing:
            existing.config_enc = _encrypt(json.dumps(config))
            existing.status     = "pending"
        else:
            integration = ERPIntegration(
                org_id       = org_id,
                provider     = "parasut",
                display_name = f"Paraşüt ({company_id})",
                status       = "pending",
                config_enc   = _encrypt(json.dumps(config)),
            )
            self.db.add(integration)

        await self.db.commit()

        # OAuth2 URL
        import urllib.parse
        params = {
            "client_id":     client_id,
            "redirect_uri":  redirect_uri,
            "response_type": "code",
            "scope":         " ".join(PARASUT_SCOPES),
            "state":         state,
        }
        auth_url = PARASUT_AUTH_URL + "?" + urllib.parse.urlencode(params)

        return {"auth_url": auth_url, "state": state}

    async def handle_callback(
        self,
        org_id: str,
        code:   str,
        state:  str,
    ) -> dict[str, Any]:
        """
        OAuth2 callback isle, token kaydet.
        """
        import httpx
        from sqlalchemy import select

        from app.models.erp_integration import ERPIntegration

        stmt = (
            select(ERPIntegration)
            .where(ERPIntegration.org_id == org_id, ERPIntegration.provider == "parasut")
        )
        integration = (await self.db.execute(stmt)).scalar_one_or_none()
        if not integration:
            raise ValueError(f"Org {org_id} icin Parasut entegrasyonu bulunamadi")

        config = json.loads(_decrypt(integration.config_enc or "{}"))

        # State dogrula
        if config.get("oauth_state") != state:
            raise ValueError("Gecersiz OAuth state — CSRF koruması")

        # Token al
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(PARASUT_TOKEN_URL, data={
                "grant_type":    "authorization_code",
                "code":          code,
                "redirect_uri":  config["redirect_uri"],
                "client_id":     config["client_id"],
                "client_secret": config["client_secret"],
            })
            resp.raise_for_status()
            token_data = resp.json()

        # Token'lari sifreli kaydet
        integration.access_token_enc  = _encrypt(token_data["access_token"])
        integration.refresh_token_enc = _encrypt(token_data.get("refresh_token", ""))
        integration.token_expires_at  = datetime.now(UTC) + timedelta(
            seconds=token_data.get("expires_in", 7200)
        )
        integration.scopes       = token_data.get("scope", " ".join(PARASUT_SCOPES))
        integration.status       = "active"
        integration.connected_at = datetime.now(UTC)

        await self.db.commit()
        logger.info("Parasut OAuth tamamlandi: org=%s", org_id)

        return integration.to_summary()

    async def refresh_token(self, integration: Any) -> None:
        """Access token'i refresh token ile yenile."""
        import httpx

        config = json.loads(_decrypt(integration.config_enc or "{}"))
        refresh_token = _decrypt(integration.refresh_token_enc or "")

        if not refresh_token:
            integration.status = "expired"
            await self.db.commit()
            raise ValueError("Refresh token yok — yeniden baglanti gerekli")

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(PARASUT_TOKEN_URL, data={
                "grant_type":    "refresh_token",
                "refresh_token": refresh_token,
                "client_id":     config["client_id"],
                "client_secret": config["client_secret"],
            })
            if resp.status_code == 401:
                integration.status = "expired"
                await self.db.commit()
                raise ValueError("Refresh token gecersiz — yeniden baglanti gerekli")
            resp.raise_for_status()
            token_data = resp.json()

        integration.access_token_enc = _encrypt(token_data["access_token"])
        if token_data.get("refresh_token"):
            integration.refresh_token_enc = _encrypt(token_data["refresh_token"])
        integration.token_expires_at = datetime.now(UTC) + timedelta(
            seconds=token_data.get("expires_in", 7200)
        )
        integration.status = "active"
        await self.db.commit()
        logger.info("Parasut token yenilendi: integration_id=%s", integration.id)

    async def sync(self, integration_id: str) -> dict[str, Any]:
        """
        Parasut'tan islemleri cek, SyncBatch olustur.
        Returns: {transactions, sync_count, errors}
        """
        import time

        from sqlalchemy import select

        from app.models.erp_integration import ERPIntegration, ERPSyncLog
        from app.services.data_sync.accounting.parasut import ParasutClient

        start = time.time()

        stmt = select(ERPIntegration).where(ERPIntegration.id == integration_id)
        integration = (await self.db.execute(stmt)).scalar_one_or_none()
        if not integration:
            raise ValueError(f"Integration {integration_id} bulunamadi")

        # Token kontrolu
        if integration.is_token_expired():
            await self.refresh_token(integration)

        config        = json.loads(_decrypt(integration.config_enc or "{}"))
        access_token  = _decrypt(integration.access_token_enc or "")
        company_id    = config.get("company_id", "")

        log = ERPSyncLog(
            integration_id = integration.id,
            org_id         = integration.org_id,
            provider       = "parasut",
            status         = "running",
            started_at     = datetime.now(UTC),
        )
        self.db.add(log)
        await self.db.commit()

        try:
            client = ParasutClient(
                client_id=config["client_id"],
                client_secret=config["client_secret"],
                refresh_token=_decrypt(integration.refresh_token_enc or ""),
                company_id=company_id,
            )
            # Prefer already-refreshed access token when present.
            if access_token:
                client._access_token = access_token
                if integration.token_expires_at:
                    client._token_expires_at = integration.token_expires_at

            date_to = datetime.now(UTC)
            date_from = date_to - timedelta(days=int(config.get("lookback_days", 90)))
            batch = await client.sync_transactions(date_from=date_from, date_to=date_to)
            tx_count = len(batch.transactions) if batch else 0

            # Integration guncelle
            integration.last_sync_at     = datetime.now(UTC)
            integration.last_sync_status = "success"
            integration.last_sync_count  = tx_count
            integration.last_error       = None

            log.status               = "success"
            log.transactions_synced  = tx_count
            log.finished_at          = datetime.now(UTC)
            log.duration_seconds     = int(time.time() - start)
            await self.db.commit()

            logger.info("Parasut sync tamamlandi: org=%s txn=%d", integration.org_id, tx_count)

            return {
                "ok":           True,
                "transactions": [
                    t.model_dump() if hasattr(t, "model_dump") else t.dict()
                    for t in (batch.transactions if batch else [])
                ],
                "sync_count":   tx_count,
                "errors":       list(batch.warnings) if batch else [],
            }

        except Exception as exc:
            err_msg = str(exc)
            integration.last_sync_at     = datetime.now(UTC)
            integration.last_sync_status = "error"
            integration.last_error       = err_msg[:500]
            log.status        = "error"
            log.error_message = err_msg[:500]
            log.finished_at   = datetime.now(UTC)
            log.duration_seconds = int(time.time() - start)
            await self.db.commit()
            logger.error("Parasut sync hatasi: org=%s err=%s", integration.org_id, exc)
            raise

    async def disconnect(self, integration_id: str) -> None:
        """Entegrasyonu devre disi birak (token'lari sil)."""
        from sqlalchemy import select

        from app.models.erp_integration import ERPIntegration

        stmt = select(ERPIntegration).where(ERPIntegration.id == integration_id)
        integration = (await self.db.execute(stmt)).scalar_one_or_none()
        if integration:
            integration.access_token_enc  = None
            integration.refresh_token_enc = None
            integration.status            = "disconnected"
            integration.disconnected_at   = datetime.now(UTC)
            await self.db.commit()
