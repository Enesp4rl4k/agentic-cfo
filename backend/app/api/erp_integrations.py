"""
ERP Integration API

GET  /erp/integrations           -- Org'un tum ERP entegrasyonlari
GET  /erp/integrations/{id}      -- Tek entegrasyon detayi
DELETE /erp/integrations/{id}    -- Entegrasyonu sil

GET  /erp/parasut/durum          -- Paraşüt açık mı, bağlı mı, firma seçilmeli mi
POST /erp/parasut/baglan         -- Paraşüt giriş adresi (platformun uygulamasıyla)
GET  /erp/parasut/callback       -- Paraşüt'ün tarayıcıyı geri gönderdiği adres (imzalı state)
POST /erp/parasut/firma          -- Birden fazla firmada hangisi
POST /erp/parasut/sync           -- Faturaları çek, analiz başlat
POST /erp/parasut/disconnect     -- Bağlantıyı kes

POST /erp/logo-tiger/connect     -- Logo Tiger entegrasyonu kaydet
POST /erp/logo-tiger/sync        -- CSV yukle ve sync et
POST /erp/mikro/sync             -- Mikro CSV sync

GET  /erp/sync-logs              -- Sync gecmisi

A sync used to feed transactions into a pipeline under a made-up job id
("erp-parasut-1a2b") with no AnalysisJob row, so nothing a page reads ever
showed the result. Synced transactions now become an ordinary analysis
through the same path as a dropped file.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.config import get_settings
from app.database import get_db
from app.models.erp_integration import ERPIntegration
from app.models.user import User
from app.services.ingest.ekle import Sahip, islemleri_ekle

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Request schemalar ─────────────────────────────────────────────────────────

class LogoTigerConnectRequest(BaseModel):
    display_name: str = Field("Logo Tiger", description="Entegrasyon gorunum adi")


class FirmaSecimi(BaseModel):
    company_id: str = Field(..., min_length=1, max_length=32)


# ── Org ID helper ─────────────────────────────────────────────────────────────

def _get_org_id(current_user: User) -> str:
    """User'dan org_id cek."""
    org_id = getattr(current_user, "org_id", None) or getattr(current_user, "organization_id", None)
    if not org_id:
        raise HTTPException(status_code=400, detail="Kullanici bir organizasyona bagli degil")
    return str(org_id)


async def _owned_integration(db: AsyncSession, integration_id: str, org_id: str) -> ERPIntegration:
    """The integration, if it is this organisation's; otherwise 404."""
    row = (await db.execute(
        select(ERPIntegration).where(ERPIntegration.id == integration_id, ERPIntegration.org_id == org_id)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Entegrasyon bulunamadi")
    return row


# ── Genel listele ─────────────────────────────────────────────────────────────

@router.get("/erp/integrations")
async def list_integrations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Organizasyonun tum ERP entegrasyonlarini listele."""
    org_id = _get_org_id(current_user)
    rows = (await db.execute(select(ERPIntegration).where(ERPIntegration.org_id == org_id))).scalars().all()
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
    return (await _owned_integration(db, integration_id, _get_org_id(current_user))).to_summary()


@router.delete("/erp/integrations/{integration_id}")
async def delete_integration(
    integration_id: str,
    current_user:   User = Depends(get_current_user),
    db:             AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Entegrasyonu ve tum loglarini sil."""
    row = await _owned_integration(db, integration_id, _get_org_id(current_user))
    await db.delete(row)
    await db.commit()
    return {"data": {"deleted_id": integration_id}, "error": None}


# ── Paraşüt ──────────────────────────────────────────────────────────────────

@router.get("/erp/parasut/durum")
async def parasut_durum(
    current_user: User = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from app.services.erp.parasut_connector import ParasutConnector, parasut_acik

    org_id = _get_org_id(current_user)
    row = (await db.execute(
        select(ERPIntegration).where(ERPIntegration.org_id == org_id, ERPIntegration.provider == "parasut")
    )).scalar_one_or_none()
    return {"data": {
        "acik": parasut_acik(),
        "baglanti": row.to_summary() if row else None,
        "firmalar": ParasutConnector.secilecek_firmalar(row) if row else [],
    }, "error": None}


@router.post("/erp/parasut/baglan")
async def parasut_baglan(
    current_user: User = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """The Paraşüt login address. The person logs in there and is sent back connected."""
    from app.services.erp.parasut_connector import ParasutAyarlanmadi, ParasutConnector

    try:
        url = await ParasutConnector(db).baslat(_get_org_id(current_user), str(current_user.id))
    except ParasutAyarlanmadi as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"data": {"auth_url": url}, "error": None}


@router.get("/erp/parasut/callback")
async def parasut_callback(
    code:  str = "",
    state: str = "",
    error: str = "",
    db:    AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Paraşüt sends the browser here. No session comes with it: the signed,
    expiring, single-use state is what identifies the organisation."""
    from app.services.erp.parasut_connector import FIRMA_SECIMI, ParasutConnector

    hedef = f"{get_settings().frontend_url.rstrip('/')}/integrations"
    if error or not code or not state:
        return RedirectResponse(f"{hedef}?parasut=iptal", status_code=303)
    try:
        _org, durum = await ParasutConnector(db).geri_donus(code, state)
    except ValueError as exc:
        logger.warning("Paraşüt callback reddedildi: %s", exc)
        return RedirectResponse(f"{hedef}?parasut=hata", status_code=303)
    return RedirectResponse(f"{hedef}?parasut={'firma_sec' if durum == FIRMA_SECIMI else 'baglandi'}",
                            status_code=303)


@router.post("/erp/parasut/firma")
async def parasut_firma(
    body:         FirmaSecimi,
    current_user: User = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from app.services.erp.parasut_connector import ParasutConnector

    org_id = _get_org_id(current_user)
    row = (await db.execute(
        select(ERPIntegration).where(ERPIntegration.org_id == org_id, ERPIntegration.provider == "parasut")
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Entegrasyon bulunamadi")
    try:
        await ParasutConnector(db).firma_sec(row, body.company_id.strip())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"data": row.to_summary(), "error": None}


@router.post("/erp/parasut/sync")
async def parasut_sync(
    integration_id: str = Form(...),
    current_user:   User = Depends(get_current_user),
    db:             AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Pull the invoices and start an analysis of them."""
    from app.services.erp.parasut_connector import ParasutConnector

    # Any integration id used to be accepted: one organisation could pull or
    # disconnect another's Paraşüt by naming its id.
    row = await _owned_integration(db, integration_id, _get_org_id(current_user))
    try:
        islemler = await ParasutConnector(db).islemleri_cek(row)
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if not islemler:
        return {"data": {"sync_count": 0, "job_id": None, "mesaj": "Son 90 günde fatura bulunamadı."}, "error": None}
    out = await islemleri_ekle(db, Sahip.kullanici(current_user), islemler, "parasut")
    return {"data": {"sync_count": len(islemler), "job_id": out["job_id"], "dosyalar": out["dosyalar"]}, "error": None}


@router.post("/erp/parasut/disconnect")
async def parasut_disconnect(
    integration_id: str,
    current_user:   User = Depends(get_current_user),
    db:             AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Parasut baglantisini kes."""
    from app.services.erp.parasut_connector import ParasutConnector

    row = await _owned_integration(db, integration_id, _get_org_id(current_user))
    await ParasutConnector(db).disconnect(row)
    return {"data": {"disconnected": True}, "error": None}


# ── Logo Tiger / Mikro ───────────────────────────────────────────────────────

def _decode(content: bytes) -> str:
    for enc in ("utf-8-sig", "cp1254"):
        try:
            return content.decode(enc)
        except UnicodeDecodeError:
            continue
    return content.decode("latin-1")


@router.post("/erp/logo-tiger/connect")
async def logo_tiger_connect(
    req:          LogoTigerConnectRequest,
    current_user: User = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Logo Tiger entegrasyon kaydı olustur."""
    from app.services.erp.logo_tiger_connector import LogoTigerConnector
    return await LogoTigerConnector(db).create_or_update_integration(
        org_id=_get_org_id(current_user), display_name=req.display_name)


async def _csv_sync(kaynak: str, file: UploadFile, current_user: User, db: AsyncSession) -> dict[str, Any]:
    from app.services.erp.logo_tiger_connector import LogoTigerConnector, MikroConnector

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Dosya boyutu 10MB sinirini asiyor")
    org_id = _get_org_id(current_user)
    connector = LogoTigerConnector(db) if kaynak == "logo_tiger" else MikroConnector(db)
    kwargs: dict[str, Any] = {"org_id": org_id, "csv_content": _decode(content)}
    if kaynak == "logo_tiger":
        kwargs["filename"] = file.filename or "upload.csv"
    sync_result = await connector.sync_from_csv(**kwargs)
    islemler = sync_result.get("transactions") or []
    sync_result["cfo_job_id"] = None
    if islemler:
        out = await islemleri_ekle(db, Sahip.kullanici(current_user), islemler, kaynak)
        sync_result["cfo_job_id"] = out["job_id"]
    return sync_result


@router.post("/erp/logo-tiger/sync")
async def logo_tiger_sync(
    file:         UploadFile = File(..., description="Logo Tiger CSV export dosyasi"),
    current_user: User = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Logo Tiger CSV (Fiş Listesi, Hesap Hareketleri, Mizan) yükle; analiz başlat."""
    return await _csv_sync("logo_tiger", file, current_user, db)


@router.post("/erp/mikro/sync")
async def mikro_sync(
    file:         UploadFile = File(..., description="Mikro ERP CSV export"),
    current_user: User = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Mikro ERP CSV dosyasini yükle; analiz başlat."""
    return await _csv_sync("mikro", file, current_user, db)


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
    stmt = select(ERPSyncLog).where(ERPSyncLog.org_id == org_id)
    if provider:
        stmt = stmt.where(ERPSyncLog.provider == provider)
    stmt = stmt.order_by(desc(ERPSyncLog.started_at)).limit(limit)
    logs = (await db.execute(stmt)).scalars().all()
    return {"data": {"logs": [log.to_dict() for log in logs]}, "error": None}
