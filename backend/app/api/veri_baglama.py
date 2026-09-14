"""Verilerimi bağla — drop files in; the system works out what they are and where they go.

POST /veri/ekle    one or more files. Each is recognised from its columns and
                   put where it belongs: a bank statement or financial
                   document starts an analysis; a staff list, campaign report
                   or risk register is attached to the company's latest
                   analysis for its domain. A file that fits more than one type
                   is not saved — the answer lists the types, and the file is
                   sent again with the person's choice in `secimler`.
GET  /veri/turler  the types a person can choose from, in plain Turkish.

The person never picks a "source type", renames a column or reformats a
number. When the system cannot tell, it says so and asks; it does not guess.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.access import load_owned_job
from app.api.auth import get_current_user
from app.config import get_settings
from app.database import get_db
from app.models.analysis_job import AnalysisJob
from app.models.data_source import DataSource
from app.models.user import User
from app.services.ingest import schemas as S
from app.services.ingest.recognize import (
    BELIRSIZ,
    FINANSAL_BELGE,
    GIT_LOG,
    KESIN,
    Tanima,
    standart_csv,
    tabloyu_sec,
    tani,
)
from app.services.ingest.table import OkunamayanDosya
from app.services.upload_service import (
    FileValidationError,
    UploadResult,
    create_analysis_job,
    validate_magic_bytes,
)
from app.services.usage_meter import UsageLimitExceeded, check_upload_limit, record_usage_event

router = APIRouter()
logger = logging.getLogger(__name__)

_MAX_DOSYA = 10
_UZANTILAR = {"csv", "xlsx", "xls", "pdf", "txt"}

EKLENDI = "eklendi"
SECIM_GEREKLI = "secim_gerekli"
TANINMADI = "taninmadi"
REDDEDILDI = "reddedildi"
FINANSAL_DOSYA_GEREKLI = "finansal_dosya_gerekli"


def _uzanti(ad: str) -> str:
    return ad.rsplit(".", 1)[-1].lower() if "." in ad else ""


def _secilebilir() -> list[dict[str, str]]:
    return [*({"tur": s.tur, "alan": s.alan, "etiket": s.etiket} for s in S.SEMALAR),
            {"tur": GIT_LOG, "alan": "cto", "etiket": "Kod geçmişi (git log)"}]


@router.get("/veri/turler")
async def veri_turleri(current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    return {"data": _secilebilir(), "error": None}


def _dosya_yaz(dizin: str, ad: str, veri: bytes) -> str:
    os.makedirs(dizin, exist_ok=True)
    yol = os.path.join(dizin, ad)
    with open(yol, "wb") as f:
        f.write(veri)
    return yol


async def _finansal_ekle(
    veri: bytes, dosya_adi: str, tanima: Tanima, user: User, db: AsyncSession,
) -> dict[str, Any]:
    """A financial file becomes an analysis job, exactly as the upload page makes one."""
    uzanti = _uzanti(dosya_adi)
    if tanima.tur == S.BANKA_EKSTRESI and uzanti in ("csv", "xlsx", "txt"):
        # The statement as its parser reads it: the header row found under the
        # bank's title rows, one signed amount, ISO dates, no totals row.
        tablo = await asyncio.to_thread(tabloyu_sec, veri, dosya_adi, S.BANKA_EKSTRESI)
        if tablo is not None:
            veri, uzanti = standart_csv(tablo, S.BANKA_EKSTRESI)[0].encode("utf-8"), "csv"
    try:
        validate_magic_bytes(uzanti, veri[:8])
    except FileValidationError as exc:
        return {"durum": REDDEDILDI, "mesaj": str(exc)}
    if user.org_id:
        try:
            await check_upload_limit(str(user.org_id), db)
        except UsageLimitExceeded as exc:
            return {"durum": REDDEDILDI, "mesaj": f"Paket limitiniz doldu: {exc}"}

    job_id = str(uuid.uuid4())
    settings = get_settings()
    yol = await asyncio.to_thread(
        _dosya_yaz, os.path.join(settings.storage_local_path, "uploads", job_id), f"document.{uzanti}", veri)
    job = await create_analysis_job(
        result=UploadResult(job_id=job_id, file_path=yol, ext=uzanti, size_bytes=len(veri)),
        user_id=str(user.id), org_id=user.org_id, db=db,
    )
    if user.org_id:
        await record_usage_event(str(user.org_id), "upload", db=db)

    dispatch = "not_requested"
    if settings.auto_enqueue_analysis_on_upload:
        try:
            from app.worker import enqueue_analysis

            dispatch = await enqueue_analysis(job.id)
        except Exception:
            logger.exception("Analysis enqueue failed for job=%s", job.id)
            dispatch = "failed"
    return {"durum": EKLENDI, "job_id": job.id, "dispatch": dispatch,
            "mesaj": "Analiz başlatıldı." if dispatch in ("queued", "inline") else
                     "Dosya kaydedildi; analiz başlatılamadı, Yükle sayfasından tekrar deneyin."}


async def _son_is(db: AsyncSession, user: User) -> AnalysisJob | None:
    if not user.org_id:
        return None
    return (await db.execute(
        select(AnalysisJob).where(AnalysisJob.org_id == user.org_id)
        .order_by(desc(AnalysisJob.created_at)).limit(1)
    )).scalar_one_or_none()


async def _alan_ekle(
    veri: bytes, dosya_adi: str, tur: str, alan: str, job: AnalysisJob, db: AsyncSession,
) -> dict[str, Any]:
    source_id = str(uuid.uuid4())
    uzanti = _uzanti(dosya_adi) or "csv"
    settings = get_settings()
    yol = await asyncio.to_thread(
        _dosya_yaz,
        os.path.join(settings.storage_local_path, "uploads", job.id, "datasources", alan),
        f"{tur}_{source_id[:8]}.{uzanti}", veri,
    )
    db.add(DataSource(id=source_id, job_id=job.id, domain=alan, source_type=tur,
                      filename=dosya_adi, file_path=yol, file_size_bytes=len(veri)))
    await db.commit()
    return {"durum": EKLENDI, "job_id": job.id, "source_id": source_id,
            "mesaj": f"{S.SEMA_BY_TUR[tur].etiket if tur in S.SEMA_BY_TUR else 'Kod geçmişi'} eklendi."}


def _tur_bilgisi(tur: str) -> tuple[str, str] | None:
    if tur == GIT_LOG:
        return GIT_LOG, "cto"
    if tur == FINANSAL_BELGE:
        return FINANSAL_BELGE, "cfo"
    sema = S.SEMA_BY_TUR.get(tur)
    return (sema.tur, sema.alan) if sema else None


@router.post("/veri/ekle", status_code=status.HTTP_201_CREATED)
async def veri_ekle(
    files: list[UploadFile] = File(..., description="Bir ya da daha fazla dosya"),
    secimler: str | None = Form(default=None, description='{"dosya adı": "tür"} — belirsiz dosyalar için'),
    job_id: str | None = Form(default=None, description="Alan dosyalarının ekleneceği analiz; boşsa en son analiz"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if len(files) > _MAX_DOSYA:
        raise HTTPException(status_code=400, detail=f"Bir seferde en fazla {_MAX_DOSYA} dosya ekleyin.")
    try:
        secim: dict[str, str] = json.loads(secimler) if secimler else {}
        if not isinstance(secim, dict):
            raise ValueError
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="secimler bir {dosya adı: tür} nesnesi olmalı.") from exc

    # Checked before anything is saved: a job that is not the caller's is a 404
    # for the whole request, not after the first files are stored.
    istenen = await load_owned_job(db, job_id, current_user) if job_id else None

    max_bytes = get_settings().max_upload_size_mb * 1024 * 1024
    okunan: list[tuple[str, bytes, Tanima, dict[str, Any]]] = []
    for f in files:
        ad = f.filename or "dosya"
        veri = await f.read()
        sonuc: dict[str, Any] = {"dosya": ad}
        if _uzanti(ad) not in _UZANTILAR:
            sonuc.update(durum=REDDEDILDI, mesaj="Bu dosya türü desteklenmiyor. Excel, CSV ya da PDF yükleyin.")
        elif len(veri) > max_bytes:
            sonuc.update(durum=REDDEDILDI, mesaj=f"Dosya {get_settings().max_upload_size_mb} MB'tan büyük.")
        tanima = await asyncio.to_thread(tani, veri, ad) if "durum" not in sonuc else Tanima(TANINMADI)
        secilen = secim.get(ad)
        if "durum" not in sonuc and secilen:
            bilgi = _tur_bilgisi(secilen)
            if bilgi is None:
                sonuc.update(durum=REDDEDILDI, mesaj=f"Bilinmeyen tür: {secilen}")
            else:
                tanima.durum, tanima.tur, tanima.alan = KESIN, bilgi[0], bilgi[1]
        okunan.append((ad, veri, tanima, sonuc))

    # Financial files first: the analysis they start is where the rest attach.
    okunan.sort(key=lambda x: 0 if x[2].alan == "cfo" else 1)
    yeni_is: str | None = None
    hedef: AnalysisJob | None = None
    dosyalar: list[dict[str, Any]] = []
    for ad, veri, tanima, sonuc in okunan:
        sonuc["tanima"] = tanima.to_dict()
        if "durum" in sonuc:
            dosyalar.append(sonuc)
            continue
        if tanima.durum == BELIRSIZ:
            sonuc.update(durum=SECIM_GEREKLI, mesaj=tanima.ozet)
        elif tanima.durum != KESIN or not tanima.tur or not tanima.alan:
            sonuc.update(durum=TANINMADI, mesaj=tanima.ozet)
        elif tanima.alan == "cfo":
            sonuc.update(await _finansal_ekle(veri, ad, tanima, current_user, db))
            if sonuc["durum"] == EKLENDI and yeni_is is None:
                yeni_is = sonuc["job_id"]
        else:
            if hedef is None:
                hedef = (await db.get(AnalysisJob, yeni_is) if yeni_is else istenen) or await _son_is(db, current_user)
            if hedef is None:
                sonuc.update(durum=FINANSAL_DOSYA_GEREKLI, mesaj=(
                    "Bu dosyanın eklenebilmesi için önce bir banka ekstresi ya da muhasebe dosyası "
                    "ekleyin; iki dosyayı birlikte de bırakabilirsiniz."))
            else:
                try:
                    sonuc.update(await _alan_ekle(veri, ad, tanima.tur, tanima.alan, hedef, db))
                except OkunamayanDosya as exc:
                    sonuc.update(durum=REDDEDILDI, mesaj=str(exc))
        if sonuc.get("durum") == EKLENDI:
            sonuc["sayfa"] = f"/{tanima.alan}"
        dosyalar.append(sonuc)

    return {"data": {"job_id": yeni_is or (hedef.id if hedef else None), "dosyalar": dosyalar}, "error": None}
