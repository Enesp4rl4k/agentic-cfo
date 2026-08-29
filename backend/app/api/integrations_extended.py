"""
Entegrasyon API — Alan 4 (INT-2, INT-4, INT-5, INT-6)

GET  /integrations/channels             → Aktif entegrasyon kanalları
POST /integrations/open-banking/connect → Open Banking banka bağla
POST /integrations/open-banking/sync    → Hesap hareketlerini çek
POST /integrations/ecommerce/sync       → E-ticaret siparişlerini çek
POST /integrations/sheets/export        → CFO sonuçlarını Sheets'e gönder
POST /integrations/sheets/import        → Sheets'ten finansal veri çek
POST /integrations/webhook/test         → Webhook bağlantısını test et
GET  /integrations/webhook/config       → Webhook ayarlarını oku
PUT  /integrations/webhook/config       → Webhook ayarlarını güncelle
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.models.user import User

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Schemas ───────────────────────────────────────────────────────────────────

class OpenBankingConnectRequest(BaseModel):
    bank:          str = Field(..., description="isbank|garanti|akbank|yapikredi")
    client_id:     str
    client_secret: str
    sandbox:       bool = True


class OpenBankingSyncRequest(BaseModel):
    bank:       str
    account_id: str
    from_date:  str = Field(..., description="YYYY-MM-DD")
    to_date:    str = Field(..., description="YYYY-MM-DD")


class EcommerceSyncRequest(BaseModel):
    channel:    str  = Field(..., description="shopify|trendyol|hepsiburada")
    from_date:  str
    to_date:    str
    # Channel-specific credentials
    credentials: dict[str, str]


class SheetsExportRequest(BaseModel):
    spreadsheet_id:  str
    job_id:          str | None = None
    range_name:      str = "CFO!A1"


class SheetsImportRequest(BaseModel):
    spreadsheet_id: str
    range_name:     str = "Sheet1!A1:Z1000"
    column_mapping: dict[str, str] | None = None  # spreadsheet col → CFO field


class WebhookConfig(BaseModel):
    slack_webhook_url:  str | None = None
    teams_webhook_url:  str | None = None
    custom_webhook_url: str | None = None
    email_recipients:   list[str]  = Field(default_factory=list)
    enabled_events:     list[str]  = Field(
        default_factory=lambda: ["analysis_complete", "kri_breach", "anomaly_detected"]
    )


class WebhookTestRequest(BaseModel):
    channel:  str   = Field(..., description="slack|teams|custom|email")
    target:   str   = Field(..., description="Webhook URL veya email adresi")
    message:  str   = "Agentic CFO — Test mesajı"


# ── Channels endpoint ─────────────────────────────────────────────────────────

@router.get("/integrations/channels")
async def list_integration_channels(
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Yapılandırılmış entegrasyon kanallarını listele."""
    from app.config import get_settings
    settings = get_settings()

    channels = []

    # Open Banking
    ob_banks = []
    for bank in ["akbank", "garanti", "isbank", "yapikredi"]:
        key   = f"openbanking_{bank}_client_id"
        value = getattr(settings, key, "")
        if value:
            ob_banks.append(bank)
    if ob_banks:
        channels.append({"id": "open_banking", "name": "Open Banking", "banks": ob_banks, "active": True})
    else:
        channels.append({"id": "open_banking", "name": "Open Banking", "active": False, "setup_url": "/settings/integrations"})

    # E-ticaret
    ecom = []
    if getattr(settings, "shopify_access_token", ""):
        ecom.append("shopify")
    if getattr(settings, "trendyol_api_key", ""):
        ecom.append("trendyol")
    channels.append({
        "id": "ecommerce", "name": "E-Ticaret", "active": bool(ecom), "channels": ecom
    })

    # Google Sheets
    channels.append({
        "id": "google_sheets",
        "name": "Google Sheets",
        "active": bool(getattr(settings, "google_sheets_service_account", "")),
    })

    # Webhooks
    channels.append({
        "id": "webhook",
        "name": "Webhook / Bildirimler",
        "active": bool(
            getattr(settings, "slack_webhook_url", "") or
            getattr(settings, "teams_webhook_url", "")
        ),
    })

    # GİB e-Fatura (already existing)
    channels.append({
        "id": "efatura",
        "name": "GİB e-Fatura",
        "active": bool(getattr(settings, "gib_vkn", "")),
        "sandbox": getattr(settings, "gib_sandbox", True),
    })

    return {"data": {"channels": channels}, "error": None}


# ── Open Banking ──────────────────────────────────────────────────────────────

@router.post("/integrations/open-banking/sync")
async def sync_open_banking(
    req:          OpenBankingSyncRequest,
    current_user: User = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Open Banking'den hesap hareketlerini çek."""
    from app.config import get_settings
    settings   = get_settings()
    client_id  = getattr(settings, f"openbanking_{req.bank}_client_id", "")
    client_sec = getattr(settings, f"openbanking_{req.bank}_client_secret", "")

    if not client_id:
        raise HTTPException(
            status_code=400,
            detail=f"'{req.bank}' için Open Banking credentials yapılandırılmamış"
        )

    from app.services.integrations import TurkiyeOpenBankingClient
    client = TurkiyeOpenBankingClient(
        bank=req.bank, client_id=client_id, client_secret=client_sec, sandbox=True
    )

    try:
        transactions = await client.get_transactions(
            req.account_id, req.from_date, req.to_date
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Open Banking API hatası: {exc}")

    return {
        "data": {
            "bank":           req.bank,
            "account_id":     req.account_id,
            "transaction_count": len(transactions),
            "transactions":   transactions[:100],  # ilk 100
        },
        "error": None,
    }


# ── E-ticaret ─────────────────────────────────────────────────────────────────

@router.post("/integrations/ecommerce/sync")
async def sync_ecommerce(
    req:          EcommerceSyncRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """E-ticaret kanalından siparişleri çek."""
    from app.services.integrations import ShopifyConnector, TrendyolConnector

    orders = []
    if req.channel == "shopify":
        token  = req.credentials.get("access_token") or req.credentials.get("api_key", "")
        domain = req.credentials.get("shop_domain", "")
        if not token or not domain:
            raise HTTPException(400, "Shopify için shop_domain ve access_token gerekli")
        conn   = ShopifyConnector(domain, token)
        orders = await conn.get_orders(req.from_date, req.to_date)

    elif req.channel == "trendyol":
        sid    = req.credentials.get("supplier_id", "")
        key    = req.credentials.get("api_key", "")
        secret = req.credentials.get("api_secret", "")
        if not sid or not key:
            raise HTTPException(400, "Trendyol için supplier_id, api_key ve api_secret gerekli")
        conn   = TrendyolConnector(sid, key, secret)
        orders = await conn.get_orders(req.from_date, req.to_date)

    else:
        raise HTTPException(400, f"Desteklenmeyen kanal: {req.channel}")

    return {
        "data": {
            "channel":     req.channel,
            "order_count": len(orders),
            "total_revenue": sum(o.get("amount_try", 0) for o in orders),
            "orders":      orders[:200],
        },
        "error": None,
    }


# ── Google Sheets ─────────────────────────────────────────────────────────────

@router.post("/integrations/sheets/export")
async def export_to_sheets(
    req:          SheetsExportRequest,
    current_user: User = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """CFO analiz sonuçlarını Google Sheets'e gönder."""
    from app.config import get_settings
    settings  = get_settings()
    sa_json   = getattr(settings, "google_sheets_service_account", "")
    if not sa_json:
        raise HTTPException(400, "Google Sheets service account yapılandırılmamış")

    from app.services.integrations import GoogleSheetsConnector
    conn = GoogleSheetsConnector(sa_json)

    # Get CFO results if job_id provided
    cfo_result: dict = {}
    if req.job_id:
        try:
            from app.models.analysis_job import AnalysisJob
            job = await db.get(AnalysisJob, req.job_id)
            if job and job.result:
                cfo_result = job.result
        except Exception:
            pass

    try:
        await conn.export_cfo_results(req.spreadsheet_id, cfo_result)
        return {
            "data": {"status": "exported", "spreadsheet_id": req.spreadsheet_id},
            "error": None,
        }
    except Exception as exc:
        raise HTTPException(502, f"Google Sheets export hatası: {exc}")


@router.post("/integrations/sheets/import")
async def import_from_sheets(
    req:          SheetsImportRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Google Sheets'ten finansal veri çek."""
    from app.config import get_settings
    settings = get_settings()
    sa_json  = getattr(settings, "google_sheets_service_account", "")
    if not sa_json:
        raise HTTPException(400, "Google Sheets service account yapılandırılmamış")

    from app.services.integrations import GoogleSheetsConnector
    conn = GoogleSheetsConnector(sa_json)

    try:
        rows = await conn.read_sheet(req.spreadsheet_id, req.range_name)
        return {
            "data": {
                "row_count": len(rows),
                "columns":   rows[0] if rows else [],
                "rows":      rows[1:100] if len(rows) > 1 else [],
            },
            "error": None,
        }
    except Exception as exc:
        raise HTTPException(502, f"Google Sheets import hatası: {exc}")


# ── Webhook ───────────────────────────────────────────────────────────────────

@router.post("/integrations/webhook/test")
async def test_webhook(
    req:          WebhookTestRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Webhook bağlantısını test et."""
    from app.services.integrations import get_webhook_dispatcher
    dispatcher = get_webhook_dispatcher()

    success = False
    if req.channel == "slack":
        success = await dispatcher.send_slack(req.target, req.message, {"Test": "✓ Bağlantı başarılı"})
    elif req.channel == "teams":
        success = await dispatcher.send_teams(req.target, "Agentic CFO Test", req.message)
    elif req.channel == "custom":
        success = await dispatcher.send_custom(req.target, {"message": req.message, "source": "agentic_cfo"})
    elif req.channel == "email":
        success = await dispatcher.send_email(req.target, "Agentic CFO — Test", f"<p>{req.message}</p>")
    else:
        raise HTTPException(400, f"Bilinmeyen kanal: {req.channel}")

    return {
        "data": {
            "channel": req.channel,
            "target":  req.target,
            "success": success,
            "message": "Webhook başarıyla gönderildi" if success else "Webhook gönderilemedi",
        },
        "error": None,
    }


@router.get("/integrations/webhook/config")
async def get_webhook_config(
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Mevcut webhook ayarlarını oku (URL'leri maskele)."""
    from app.config import get_settings
    settings = get_settings()

    def mask(url: str) -> str | None:
        if not url:
            return None
        return url[:20] + "..." if len(url) > 20 else url

    return {
        "data": {
            "slack_configured":  bool(getattr(settings, "slack_webhook_url", "")),
            "teams_configured":  bool(getattr(settings, "teams_webhook_url", "")),
            "custom_configured": bool(getattr(settings, "custom_webhook_url", "")),
            "slack_preview":     mask(getattr(settings, "slack_webhook_url", "")),
            "teams_preview":     mask(getattr(settings, "teams_webhook_url", "")),
        },
        "error": None,
    }
