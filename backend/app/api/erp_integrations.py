"""
ERP Integration API

GET  /erp/integrations           -- Org'un tum ERP entegrasyonlari
POST /erp/parasut/connect        -- Parasut OAuth2 URL al
GET  /erp/parasut/callback       -- OAuth2 callback isle
POST /erp/parasut/sync           -- Manuel sync tetikle
POST /erp/parasut/disconnect     -- Baglantıyı kes

POST /erp/logo-tiger/connect     -- Logo Tiger entegrasyonu kaydet
POST /erp/logo-tiger/sync        -- CSV yukle ve sync et
POST /erp/mikro/sync             -- Mikro CSV sync

GET  /erp/sync-logs              -- Sync gecmisi
GET  /erp/integrations/{id}      -- Tek entegrasyon detayi
DELETE /erp/integrations/{id}    -- Entegrasyonu sil
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.models.user import User

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Request schemalar ─────────────────────────────────────────────────────────

class ParasutConnectRequest(BaseModel):
    client_id:     str = Field(..., description="Parasut uygulama client_id")
    client_secret: str = Field(..., description="Parasut uygulama client_secret")
    company_id:    str = Field(..., description="Parasut firma ID'si")
    redirect_uri:  str = Field(..., description="OAuth2 callback URL")


class LogoTigerConnectRequest(BaseModel):
    display_name: str = Field("Logo Tiger", description="Entegrasyon gorunum adi")


# ── Org ID helper ─────────────────────────────────────────────────────────────

def _get_org_id(current_user: User) -> str:
    """User'dan org_id cek."""
    org_id = getattr(current_user, "org_id", None) or getattr(current_user, "organization_id", None)
    if not org_id:
        raise HTTPException(status_code=400, detail="Kullanici bir organizasyona bagli degil")
    return str(org_id)


# ── Genel listele ─────────────────────────────────────────────────────────────

@router.get("/erp/integrations")
async def list_integrations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Organizasyonun tum ERP entegrasyonlarini listele."""
    from app.models.erp_integration import ERPIntegration

    org_id = _get_org_id(current_user)
    stmt   = select(ERPIntegration).where(ERPIntegration.org_id == org_id)
    rows   = (await db.execute(stmt)).scalars().all()

    return {
        "integrations": [r.to_summary() for r in rows],
        "providers":    ["parasut", "logo_tiger", "mikro", "netsis"],
    }


@router.get("/erp/integrations/{integration_id}")
async def get_integration(
    integration_id: str,
    current_user:   User = Depends(get_current_user),
    db:             AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Tek entegrasyon detayi."""
    from app.models.erp_integration import ERPIntegration

    org_id = _get_org_id(current_user)
    stmt   = select(ERPIntegration).where(
        ERPIntegration.id     == integration_id,
        ERPIntegration.org_id == org_id,
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Entegrasyon bulunamadi")
    return row.to_summary()


@router.delete("/erp/integrations/{integration_id}")
async def delete_integration(
    integration_id: str,
    current_user:   User = Depends(get_current_user),
    db:             AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Entegrasyonu ve tum loglarini sil."""
    from app.models.erp_integration import ERPIntegration

    org_id = _get_org_id(current_user)
    stmt   = select(ERPIntegration).where(
        ERPIntegration.id     == integration_id,
        ERPIntegration.org_id == org_id,
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Entegrasyon bulunamadi")
    await db.delete(row)
    await db.commit()
    return {"data": {"deleted_id": integration_id}, "error": None}


# ── Parasut endpoints ─────────────────────────────────────────────────────────

@router.post("/erp/parasut/connect")
async def parasut_connect(
    req:          ParasutConnectRequest,
    current_user: User = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Parasut OAuth2 baglantisi baslat.
    Dondurulen auth_url'e kullanicıyı yonlendir.
    """
    from app.services.erp.parasut_connector import ParasutConnector
    org_id    = _get_org_id(current_user)
    connector = ParasutConnector(db)
    try:
        return await connector.get_auth_url(
            org_id=org_id,
            client_id=req.client_id,
            client_secret=req.client_secret,
            redirect_uri=req.redirect_uri,
            company_id=req.company_id,
        )
    except Exception as exc:
        logger.exception("Parasut connect hatasi: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/erp/parasut/callback")
async def parasut_callback(
    code:         str,
    state:        str,
    current_user: User = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Parasut OAuth2 callback.
    Bu endpoint Parasut tarafından redirect_uri olarak cagirilir.
    """
    from app.services.erp.parasut_connector import ParasutConnector
    org_id    = _get_org_id(current_user)
    connector = ParasutConnector(db)
    try:
        return await connector.handle_callback(org_id=org_id, code=code, state=state)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Parasut callback hatasi: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/erp/parasut/sync")
async def parasut_sync(
    integration_id: str = Form(...),
    current_user:   User = Depends(get_current_user),
    db:             AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Parasut'tan manuel sync tetikle."""
    from app.agents.orchestration.erp_sync_runner import run_erp_sync_and_analyze
    from app.services.erp.parasut_connector import ParasutConnector

    org_id    = _get_org_id(current_user)
    connector = ParasutConnector(db)
    try:
        sync_result = await connector.sync(integration_id)
        # CFO pipeline'a otomatik besle
        if sync_result.get("transactions"):
            cfo_job = await run_erp_sync_and_analyze(
                org_id=org_id,
                transactions=sync_result["transactions"],
                source="parasut",
                db=db,
            )
            sync_result["cfo_job_id"] = cfo_job.get("job_id")
        return sync_result
    except Exception as exc:
        logger.exception("Parasut sync hatasi: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/erp/parasut/disconnect")
async def parasut_disconnect(
    integration_id: str,
    current_user:   User = Depends(get_current_user),
    db:             AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Parasut baglantisini kes."""
    from app.services.erp.parasut_connector import ParasutConnector
    connector = ParasutConnector(db)
    await connector.disconnect(integration_id)
    return {"data": {"disconnected": True}, "error": None}


# ── Logo Tiger endpoints ──────────────────────────────────────────────────────

@router.post("/erp/logo-tiger/connect")
async def logo_tiger_connect(
    req:          LogoTigerConnectRequest,
    current_user: User = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Logo Tiger entegrasyon kaydı olustur."""
    from app.services.erp.logo_tiger_connector import LogoTigerConnector
    org_id    = _get_org_id(current_user)
    connector = LogoTigerConnector(db)
    return await connector.create_or_update_integration(org_id=org_id, display_name=req.display_name)


@router.post("/erp/logo-tiger/sync")
async def logo_tiger_sync(
    file:         UploadFile = File(..., description="Logo Tiger CSV export dosyasi"),
    current_user: User = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Logo Tiger CSV dosyasini yukle ve sync et.

    Desteklenen formatlar:
    - Fis Listesi (Tarih;Fis No;Aciklama;Borc;Alacak;Bakiye)
    - Hesap Hareketleri
    - Mizan Raporu
    """
    from app.agents.orchestration.erp_sync_runner import run_erp_sync_and_analyze
    from app.services.erp.logo_tiger_connector import LogoTigerConnector

    org_id = _get_org_id(current_user)

    # Dosya boyutu kontrolu (max 10MB)
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Dosya boyutu 10MB sinirini asyiyor")

    try:
        csv_text  = content.decode("utf-8-sig")  # BOM'lu UTF-8 destekle
    except UnicodeDecodeError:
        try:
            csv_text = content.decode("cp1254")   # Windows Turkce
        except UnicodeDecodeError:
            csv_text = content.decode("latin-1")

    connector   = LogoTigerConnector(db)
    sync_result = await connector.sync_from_csv(
        org_id=org_id,
        csv_content=csv_text,
        filename=file.filename or "upload.csv",
    )

    # CFO pipeline'a otomatik besle
    if sync_result.get("transactions"):
        try:
            cfo_job = await run_erp_sync_and_analyze(
                org_id=org_id,
                transactions=sync_result["transactions"],
                source="logo_tiger",
                db=db,
            )
            sync_result["cfo_job_id"] = cfo_job.get("job_id")
        except Exception as exc:
            logger.warning("CFO pipeline besleme hatasi: %s", exc)
            sync_result["cfo_job_id"] = None

    return sync_result


# ── Mikro ERP endpoint ────────────────────────────────────────────────────────

@router.post("/erp/mikro/sync")
async def mikro_sync(
    file:         UploadFile = File(..., description="Mikro ERP CSV export"),
    current_user: User = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Mikro ERP CSV dosyasini sync et."""
    from app.agents.orchestration.erp_sync_runner import run_erp_sync_and_analyze
    from app.services.erp.logo_tiger_connector import MikroConnector

    org_id  = _get_org_id(current_user)
    content = await file.read()
    try:
        csv_text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        csv_text = content.decode("cp1254")

    connector   = MikroConnector(db)
    sync_result = await connector.sync_from_csv(org_id=org_id, csv_content=csv_text)

    if sync_result.get("transactions"):
        try:
            cfo_job = await run_erp_sync_and_analyze(
                org_id=org_id, transactions=sync_result["transactions"],
                source="mikro", db=db,
            )
            sync_result["cfo_job_id"] = cfo_job.get("job_id")
        except Exception:
            sync_result["cfo_job_id"] = None

    return sync_result


# ── Sync logs ─────────────────────────────────────────────────────────────────

@router.get("/erp/sync-logs")
async def get_sync_logs(
    provider:     str | None = None,
    limit:        int = 20,
    current_user: User = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Son sync loglarini getir."""
    from app.models.erp_integration import ERPSyncLog

    org_id = _get_org_id(current_user)
    stmt   = (
        select(ERPSyncLog)
        .where(ERPSyncLog.org_id == org_id)
    )
    if provider:
        stmt = stmt.where(ERPSyncLog.provider == provider)
    stmt = stmt.order_by(desc(ERPSyncLog.started_at)).limit(limit)
    logs = (await db.execute(stmt)).scalars().all()
    return {"data": {"logs": [log.to_dict() for log in logs]}, "error": None}
