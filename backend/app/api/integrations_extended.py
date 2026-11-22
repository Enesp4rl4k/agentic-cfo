"""
Entegrasyon API — Alan 4 (INT-2, INT-4, INT-5, INT-6)

GET  /integrations/channels             → Aktif entegrasyon kanalları
POST /integrations/open-banking/connect → Open Banking banka bağla
POST /integrations/ecommerce/sync       → E-ticaret siparişlerini çek
POST /integrations/sheets/export        → CFO sonuçlarını Sheets'e gönder
POST /integrations/sheets/import        → Sheets'ten finansal veri çek
POST /integrations/webhook/test         → Webhook bağlantısını test et
GET  /integrations/webhook/config       → Webhook ayarlarını oku
PUT  /integrations/webhook/config       → Webhook ayarlarını güncelle
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.access import can_access, require_writer
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


class EcommerceSyncRequest(BaseModel):
    channel:    str  = Field(..., description="shopify|trendyol")
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

# POST /integrations/open-banking/sync was removed. It fetched movements for any
# `account_id` the caller named, using the platform's own bank credentials and
# no consent token of the account holder — once those credentials were
# configured, one organisation could read another's bank account. Nothing in
# the frontend called it. /open-banking/connections/{id}/sync, which requires
# the holder's OAuth token, is the path.


# ── E-ticaret ─────────────────────────────────────────────────────────────────

@router.post("/integrations/ecommerce/sync",
    dependencies=[Depends(require_writer)])
async def sync_ecommerce(
    req:          EcommerceSyncRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """E-ticaret kanalından siparişleri çek."""
    from app.services.integrations import ShopifyConnector, TrendyolConnector

    if req.channel == "shopify":
        token  = req.credentials.get("access_token") or req.credentials.get("api_key", "")
        domain = req.credentials.get("shop_domain", "")
        if not token or not domain:
            raise HTTPException(400, "Shopify için shop_domain ve access_token gerekli")
        result = await ShopifyConnector(domain, token).get_orders(req.from_date, req.to_date)

    elif req.channel == "trendyol":
        sid    = req.credentials.get("supplier_id", "")
        key    = req.credentials.get("api_key", "")
        secret = req.credentials.get("api_secret", "")
        if not sid or not key:
            raise HTTPException(400, "Trendyol için supplier_id, api_key ve api_secret gerekli")
        result = await TrendyolConnector(sid, key, secret).get_orders(req.from_date, req.to_date)

    else:
        raise HTTPException(400, f"Desteklenmeyen kanal: {req.channel}")

    outcome = result.outcome()
    if result.failed:
        # An outage or a refusal is a failed sync, not a shop with no orders.
        raise HTTPException(502, f"{req.channel} siparişleri alınamadı: {result.failed}")

    # Totals count only the orders whose amount, direction and date the channel stated, per currency
    # (a lira order and a euro order are not added); the rest are counted and listed, not summed as zero.
    totals: dict[str, int] = {}
    for o in result.rows:
        if not o["feed_flags"]:
            totals[o["currency"] or ""] = totals.get(o["currency"] or "", 0) + int(o["amount_cents"])
    return {
        "data": {
            "channel":     req.channel,
            "order_count": len(result.rows),
            "sync_status": outcome["status"],
            "period_covered": outcome["complete"],
            "reason":      outcome["reason"],
            "counts":      outcome["counts"],
            "held_candidates": outcome["held_candidates"],
            "total_revenue_cents_by_currency": totals,
            "orders":      result.rows[:200],
        },
        "error": None,
    }


# ── Google Sheets ─────────────────────────────────────────────────────────────

@router.post("/integrations/sheets/export", dependencies=[Depends(require_writer)])
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
            # Exported to a spreadsheet the caller chooses — another
            # organisation's results included, before this check.
            if job and not can_access(current_user, org_id=job.org_id, user_id=job.user_id):
                job = None
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


@router.post("/integrations/sheets/import",
    dependencies=[Depends(require_writer)])
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

@router.post("/integrations/webhook/test", dependencies=[Depends(require_writer)])
async def test_webhook(
    req:          WebhookTestRequest,
    current_user: User = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Queue a fixed connection-test message to a destination (a connection-test outbox row).

    The text is fixed and the destination is checked: an https URL that is not an internal
    address, or an e-mail address the organisation may be mailed (a member or a listed recipient).
    The outbox sender delivers it and records the outcome; this route reports it queued."""
    from app.services import outbox, outbox_immediate

    channels = {"slack": "slack", "teams": "webhook", "custom": "webhook", "email": "email"}
    channel = channels.get(req.channel)
    if channel is None:
        raise HTTPException(400, f"Bilinmeyen kanal: {req.channel}")
    if not current_user.org_id:
        raise HTTPException(400, "Organizasyona üye değilsiniz.")
    try:
        row = await outbox_immediate.enqueue_connection_test(
            db, test_id=uuid.uuid4().hex, org_id=str(current_user.org_id), channel=channel,
            destination=req.target,
        )
    except outbox_immediate.ImmediateKindRefused as exc:
        raise HTTPException(400, f"Hedef kullanılamaz: {exc}") from exc
    await db.commit()
    outbox.kick()
    success = False  # queued, not delivered: the outbox row records what happened

    return {
        "data": {
            "channel": req.channel,
            "target":  req.target,
            "success": success,
            "queued":  True,
            "outbox_id": row.id,
            "message": "Test mesajı gönderim kuyruğuna alındı; sonucu giden kutusunda görünür.",
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
