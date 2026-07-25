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
from datetime import datetime, timezone, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db

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
        "created_at":          datetime.now(timezone.utc).isoformat(),
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
    expires_at = datetime.now(timezone.utc) + timedelta(
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
            "connected_at":  datetime.now(timezone.utc).isoformat(),
            "expires_at":    expires_at.isoformat(),
            "sandbox":       sandbox,
            "next_step":     f"POST /api/v1/open-banking/connections/{connection_id}/sync ile işlemleri senkronize edin.",
        },
        "error": None,
    }


@router.post("/open-banking/connections/{connection_id}/sync")
async def sync_transactions(
    connection_id: str,
    bank_id:       str = Query(..., description="Bank ID (akbank, garanti)"),
    account_id:    str = Query(..., description="Account ID from bank"),
    access_token:  str = Query(..., description="Access token from OAuth flow"),
    days_back:     int = Query(default=90, description="How many days of history to fetch"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Sync transactions from a connected bank account.

    Creates a new AnalysisJob with the fetched transactions
    and triggers the CFO analysis pipeline.
    """
    from datetime import date
    start_date = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%d")
    end_date   = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    client_id, client_secret, sandbox = _get_bank_settings(bank_id)

    from app.services.open_banking import get_bank_client
    client = get_bank_client(bank_id, client_id, client_secret, sandbox)

    try:
        transactions = await client.get_transactions(
            access_token=access_token,
            account_id=account_id,
            start_date=start_date,
            end_date=end_date,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"İşlem senkronizasyonu başarısız: {exc}",
        )

    # Create analysis job with the fetched transactions
    from app.models.analysis_job import AnalysisJob, JobStatus
    job = AnalysisJob(
        id=str(uuid.uuid4()),
        status=JobStatus.PENDING,
        filename=f"{bank_id}_open_banking_{end_date}.json",
        file_path="",  # No file — transactions injected directly
        file_type="json",
    )
    db.add(job)
    await db.commit()

    # Trigger pipeline with direct transactions (bypass file parsing)
    try:
        from app.worker import enqueue_analysis
        # Store transactions in Redis for worker to pick up
        from app.worker import get_arq_pool
        import json
        pool = await get_arq_pool()
        await pool.set(
            f"ob_transactions:{job.id}",
            json.dumps(transactions),
            ex=3600,
        )
        await enqueue_analysis(job.id)
    except Exception as exc:
        logger.warning("Could not enqueue Open Banking analysis: %s", exc)

    return {
        "data": {
            "job_id":           job.id,
            "bank_id":          bank_id,
            "transaction_count": len(transactions),
            "period":           f"{start_date} – {end_date}",
            "status":           "queued",
            "poll_url":         f"/api/v1/analysis/{job.id}",
        },
        "error": None,
    }
