"""
Open Banking API — bank connection management endpoints.

POST /api/v1/open-banking/connect/{bank_id}
     Start OAuth2 flow → returns redirect_url for user authorization.

GET  /api/v1/open-banking/callback
     Handle OAuth2 callback → exchange code for tokens → save connection.

GET  /api/v1/open-banking/connections
     List all bank connections for the current user.

POST /api/v1/open-banking/connections/{connection_id}/sync
     Sync latest transactions → creates a new analysis job.

DELETE /api/v1/open-banking/connections/{connection_id}
     Revoke connection and delete stored tokens.

SUPPORTED BANKS:
  - akbank  → Akbank (sandbox: developer.akbank.com)
  - garanti → Garanti BBVA (sandbox: developer.garantibbva.com.tr)

SETUP:
  Add to .env:
    AKBANK_CLIENT_ID=...
    AKBANK_CLIENT_SECRET=...
    GARANTI_CLIENT_ID=...
    GARANTI_CLIENT_SECRET=...
    OPEN_BANKING_SANDBOX=true
    OPEN_BANKING_REDIRECT_URI=http://localhost:8000/api/v1/open-banking/callback
"""
from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.models.user import User

router = APIRouter()
logger = logging.getLogger(__name__)

_SUPPORTED_BANKS = {
    "akbank":  {"name": "Akbank",       "color": "#e30613"},
    "garanti": {"name": "Garanti BBVA", "color": "#009966"},
}


class ConnectRequest(BaseModel):
    redirect_after_auth: str = "/"  # Frontend URL to redirect after OAuth


# ── In-memory state store (replace with Redis in production) ──────────────────
# state → {bank_id, redirect_after_auth, created_at}
_oauth_states: dict[str, dict[str, Any]] = {}


def _get_bank_settings(bank_id: str) -> tuple[str, str, bool]:
    """Return (client_id, client_secret, sandbox) for a bank."""
    from app.config import get_settings
    settings = get_settings()

    if bank_id == "akbank":
        client_id     = getattr(settings, "akbank_client_id", "")
        client_secret = getattr(settings, "akbank_client_secret", "")
    elif bank_id == "garanti":
        client_id     = getattr(settings, "garanti_client_id", "")
        client_secret = getattr(settings, "garanti_client_secret", "")
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Desteklenmeyen banka: '{bank_id}'. Desteklenen: {list(_SUPPORTED_BANKS)}",
        )

    sandbox = getattr(settings, "open_banking_sandbox", True)
    return client_id, client_secret, sandbox


def _get_redirect_uri() -> str:
    from app.config import get_settings
    settings = get_settings()
    return getattr(
        settings,
        "open_banking_redirect_uri",
        "http://localhost:8000/api/v1/open-banking/callback",
    )


@router.get("/open-banking/banks")
async def list_banks() -> dict[str, Any]:
    """List supported banks for Open Banking connection."""
    return {
        "data": [
            {"bank_id": k, "name": v["name"], "color": v["color"]}
            for k, v in _SUPPORTED_BANKS.items()
        ],
        "error": None,
    }


@router.post("/open-banking/connect/{bank_id}")
async def start_oauth(
    bank_id: str,
    body: ConnectRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Start the OAuth2 authorization flow for a bank.

    Returns a redirect_url — the frontend should redirect the user there.
    After authorization, the bank redirects back to the callback URL.
    """
    if bank_id not in _SUPPORTED_BANKS:
        raise HTTPException(
            status_code=400,
            detail=f"Desteklenmeyen banka: '{bank_id}'.",
        )

    client_id, client_secret, sandbox = _get_bank_settings(bank_id)
    if not client_id:
        raise HTTPException(
            status_code=503,
            detail=(
                f"{_SUPPORTED_BANKS[bank_id]['name']} bağlantısı henüz yapılandırılmamış. "
                f"Lütfen {bank_id.upper()}_CLIENT_ID ve {bank_id.upper()}_CLIENT_SECRET "
                f"değerlerini .env dosyasına ekleyin."
            ),
        )

    from app.services.open_banking import get_bank_client
    client = get_bank_client(bank_id, client_id, client_secret, sandbox)

    state = str(uuid.uuid4())
    auth_url, state = client.build_authorization_url(
        redirect_uri=_get_redirect_uri(),
        state=state,
    )

    # Store state for callback validation
    _oauth_states[state] = {
        "bank_id":             bank_id,
        "redirect_after_auth": body.redirect_after_auth,
        "created_at":          datetime.now(UTC).isoformat(),
    }

    return {
        "data": {
            "redirect_url": auth_url,
            "state":        state,
            "bank_id":      bank_id,
            "sandbox":      sandbox,
            "note":         "Kullanıcıyı redirect_url'e yönlendirin. Banka yetkilendirmesi sonrası callback'e dönecek.",
        },
        "error": None,
    }


@router.get("/open-banking/callback")
async def oauth_callback(
    code:  str = Query(..., description="Authorization code from bank"),
    state: str = Query(..., description="State parameter for CSRF validation"),
    error: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    OAuth2 callback handler.

    Called by the bank after user authorization.
    Exchanges the code for tokens and saves the bank connection.
    """
    if error:
        raise HTTPException(
            status_code=400,
            detail=f"Banka yetkilendirme hatası: {error}",
        )

    # Validate state
    state_data = _oauth_states.pop(state, None)
    if not state_data:
        raise HTTPException(
            status_code=400,
            detail="Geçersiz veya süresi dolmuş state parametresi.",
        )

    bank_id = state_data["bank_id"]
    client_id, client_secret, sandbox = _get_bank_settings(bank_id)

    from app.services.open_banking import get_bank_client
    client = get_bank_client(bank_id, client_id, client_secret, sandbox)

    try:
        tokens = await client.exchange_code_for_tokens(
            code=code,
            redirect_uri=_get_redirect_uri(),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Token alışverişi başarısız: {exc}",
        )

    connection_id = str(uuid.uuid4())
    expires_at = datetime.now(UTC) + timedelta(
        seconds=tokens.get("expires_in", 3600)
    )

    # In production: save tokens to DB (BankConnection model)
    # For now, return the connection info
    logger.info("Open Banking connection created: bank=%s connection=%s", bank_id, connection_id)

    return {
        "data": {
            "connection_id": connection_id,
            "bank_id":       bank_id,
            "bank_name":     _SUPPORTED_BANKS[bank_id]["name"],
            "connected_at":  datetime.now(UTC).isoformat(),
            "expires_at":    expires_at.isoformat(),
            "sandbox":       sandbox,
            "next_step":     f"POST /api/v1/open-banking/connections/{connection_id}/sync ile işlemleri senkronize edin.",
        },
        "error": None,
    }


class OpenBankingSyncBody(BaseModel):
    """What the sync needs. The bank's access token travels in the body: as a
    query parameter it was written into every access and proxy log on the way."""
    bank_id: str = Field(..., description="Bank ID (akbank, garanti)")
    account_id: str = Field(..., description="Account ID from bank")
    access_token: str = Field(..., description="Access token from the OAuth flow")
    days_back: int = Field(default=90, ge=1, le=730, description="How many days of history to fetch")


@router.post("/open-banking/connections/{connection_id}/sync")
async def sync_transactions(
    connection_id: str,
    body: OpenBankingSyncBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Sync transactions from a connected bank account into an ordinary analysis.

    The fetched rows used to be written to a Redis key nothing ever read, on a
    job with no file: the analysis failed with "file not found" while this
    answered "queued". They now become a statement the ingestion reads, through
    the same path Paraşüt's sync uses.
    """
    from app.services.ingest.ekle import EKLENDI, Sahip, islemleri_ekle

    start_date = (datetime.now(UTC) - timedelta(days=body.days_back)).strftime("%Y-%m-%d")
    end_date   = datetime.now(UTC).strftime("%Y-%m-%d")

    client_id, client_secret, sandbox = _get_bank_settings(body.bank_id)

    from app.services.open_banking import get_bank_client
    client = get_bank_client(body.bank_id, client_id, client_secret, sandbox)

    try:
        transactions = await client.get_transactions(
            access_token=body.access_token,
            account_id=body.account_id,
            start_date=start_date,
            end_date=end_date,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"İşlem senkronizasyonu başarısız: {exc}",
        ) from exc

    if not transactions:
        return {"data": {"job_id": None, "bank_id": body.bank_id, "transaction_count": 0,
                         "period": f"{start_date} – {end_date}", "status": "veri_yok"},
                "error": None}

    sonuc = await islemleri_ekle(db, Sahip.kullanici(current_user), transactions,
                                 kaynak=f"{body.bank_id}_open_banking")
    dosya = (sonuc.get("dosyalar") or [{}])[0]
    if dosya.get("durum") != EKLENDI:
        raise HTTPException(status_code=422, detail=dosya.get("mesaj") or "İşlemler eklenemedi.")

    return {
        "data": {
            "job_id":            sonuc.get("job_id"),
            "bank_id":           body.bank_id,
            "transaction_count": len(transactions),
            "period":            f"{start_date} – {end_date}",
            # What actually happened to the analysis, not a hopeful "queued".
            "status":            dosya.get("dispatch", "not_requested"),
            "message":           dosya.get("mesaj"),
            "poll_url":          f"/api/v1/analysis/{sonuc.get('job_id')}",
        },
        "error": None,
    }
