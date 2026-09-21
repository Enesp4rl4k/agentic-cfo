"""Put recognised files where they belong — for the page, the mail inbox and connector syncs.

A financial file starts an analysis exactly as the upload page does; a domain
file (staff list, campaign report, risk register) is attached to the analysis
started alongside it, or to the organisation's latest. A file that needs a
person's choice is reported as such and not saved.
"""
from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import logging
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.analysis_job import AnalysisJob
from app.models.data_source import DataSource, DataSourceDomain, DataSourceType
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
    validate_xml_payload,
)
from app.services.usage_meter import UsageLimitExceeded, check_upload_limit, record_usage_event

logger = logging.getLogger(__name__)

_MAX_DOSYA = 10
_UZANTILAR = {"csv", "xlsx", "xls", "pdf", "txt", "xml"}

EKLENDI = "eklendi"
SECIM_GEREKLI = "secim_gerekli"
TANINMADI = "taninmadi"
REDDEDILDI = "reddedildi"
FINANSAL_DOSYA_GEREKLI = "finansal_dosya_gerekli"
MUKERRER = "mukerrer"


def _uzanti(ad: str) -> str:
    return ad.rsplit(".", 1)[-1].lower() if "." in ad else ""


def secilebilir_turler() -> list[dict[str, str]]:
    return [*({"tur": s.tur, "alan": s.alan, "etiket": s.etiket} for s in S.SEMALAR),
            {"tur": GIT_LOG, "alan": "cto", "etiket": "Kod geçmişi (git log)"}]


def _dosya_yaz(dizin: str, ad: str, veri: bytes) -> str:
    os.makedirs(dizin, exist_ok=True)
    yol = os.path.join(dizin, ad)
    with open(yol, "wb") as f:
        f.write(veri)
    return yol


@dataclass(frozen=True)
class Sahip:
    """Who the files are added for: the uploader, or an organisation's mail address."""
    org_id: str | None
    user_id: str | None

    @classmethod
    def kullanici(cls, user: Any) -> Sahip:
        return cls(str(user.org_id) if user.org_id else None, str(user.id))


async def _finansal_ekle(
    veri: bytes, dosya_adi: str, tanima: Tanima, sahip: Sahip, db: AsyncSession,
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
    if sahip.org_id:
        try:
            await check_upload_limit(sahip.org_id, db)
        except UsageLimitExceeded as exc:
            return {"durum": REDDEDILDI, "mesaj": f"Paket limitiniz doldu: {exc}"}

    job_id = str(uuid.uuid4())
    settings = get_settings()
    yol = await asyncio.to_thread(
        _dosya_yaz, os.path.join(settings.storage_local_path, "uploads", job_id), f"document.{uzanti}", veri)
    job = await create_analysis_job(
        result=UploadResult(job_id=job_id, file_path=yol, ext=uzanti, size_bytes=len(veri),
                            original_name=dosya_adi),
        user_id=sahip.user_id, org_id=sahip.org_id, db=db,
    )
    if sahip.org_id:
        await record_usage_event(sahip.org_id, "upload", db=db)

    # The analysis is started once, after every file in this request has been
    # attached (see dosyalari_ekle). Starting it here meant three invoices
    # dropped together ran three analyses, each with its own review to clear.
    return {"durum": EKLENDI, "job_id": job.id, "mesaj": "Eklendi."}


async def _analizi_baslat(job_id: str) -> tuple[str, str]:
    """Queue the analysis for a job whose documents are all in place."""
    if not get_settings().auto_enqueue_analysis_on_upload:
        return "not_requested", "Dosya kaydedildi."
    try:
        from app.worker import enqueue_analysis

        dispatch = await enqueue_analysis(job_id)
    except Exception:
        logger.exception("Analysis enqueue failed for job=%s", job_id)
        dispatch = "failed"
    return dispatch, ("Analiz başlatıldı." if dispatch in ("queued", "inline") else
                      "Dosya kaydedildi; analiz başlatılamadı, Yükle sayfasından tekrar deneyin.")


async def _ek_belge_ekle(
    veri: bytes, dosya_adi: str, job: AnalysisJob, db: AsyncSession,
) -> dict[str, Any]:
    """Another financial document for an analysis that already exists."""
    source_id = str(uuid.uuid4())
    uzanti = _uzanti(dosya_adi) or "pdf"
    yol = await asyncio.to_thread(
        _dosya_yaz,
        os.path.join(get_settings().storage_local_path, "uploads", job.id, "belgeler"),
        f"{source_id[:8]}.{uzanti}", veri,
    )
    db.add(DataSource(id=source_id, job_id=job.id, domain=DataSourceDomain.CFO,
                      source_type=DataSourceType.FINANCIAL_DOCUMENT,
                      filename=dosya_adi, file_path=yol, file_size_bytes=len(veri)))
    await db.commit()
    return {"durum": EKLENDI, "job_id": job.id, "source_id": source_id,
            "mesaj": "Aynı analize eklendi."}


async def _son_is(db: AsyncSession, sahip: Sahip) -> AnalysisJob | None:
    if not sahip.org_id:
        return None
    return (await db.execute(
        select(AnalysisJob).where(AnalysisJob.org_id == sahip.org_id)
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


async def dosyalari_ekle(
    db: AsyncSession,
    sahip: Sahip,
    gelen: list[tuple[str, bytes]],
    secim: dict[str, str] | None = None,
    istenen: AnalysisJob | None = None,
) -> dict[str, Any]:
    """Recognise each file and put it where it belongs. Shared by the page and the mail inbox."""
    secim = secim or {}
    max_bytes = get_settings().max_upload_size_mb * 1024 * 1024
    okunan: list[tuple[str, bytes, Tanima, dict[str, Any]]] = []
    for ad, veri in gelen:
        sonuc: dict[str, Any] = {"dosya": ad}
        if _uzanti(ad) not in _UZANTILAR:
            sonuc.update(durum=REDDEDILDI,
                         mesaj="Bu dosya türü desteklenmiyor. Excel, CSV, PDF ya da e-Fatura XML yükleyin.")
        elif len(veri) > max_bytes:
            sonuc.update(durum=REDDEDILDI, mesaj=f"Dosya {get_settings().max_upload_size_mb} MB'tan büyük.")
        elif _uzanti(ad) == "xml":
            # Checked at the door, before anything parses it.
            try:
                validate_xml_payload(veri)
            except FileValidationError as exc:
                sonuc.update(durum=REDDEDILDI, mesaj=str(exc))
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
    # Every financial document in this request belongs to one analysis; an
    # explicit job_id says which one, otherwise the first file opens it.
    hedef_finansal: AnalysisJob | None = istenen
    gorulen: set[str] = set()
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
            imza = hashlib.sha256(veri).hexdigest()
            if imza in gorulen:
                sonuc.update(durum=MUKERRER,
                             mesaj="Bu dosya bu gönderimde bir kez daha var; bir kez eklendi.")
            else:
                gorulen.add(imza)
                if hedef_finansal is None:
                    sonuc.update(await _finansal_ekle(veri, ad, tanima, sahip, db))
                    if sonuc["durum"] == EKLENDI:
                        yeni_is = sonuc["job_id"]
                        hedef_finansal = await db.get(AnalysisJob, yeni_is)
                else:
                    # The same analysis, one more document.
                    sonuc.update(await _ek_belge_ekle(veri, ad, hedef_finansal, db))
        else:
            if hedef is None:
                hedef = (await db.get(AnalysisJob, yeni_is) if yeni_is else istenen) or await _son_is(db, sahip)
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

    # One start for the whole request, once every document is attached.
    if hedef_finansal is not None and any(d.get("durum") == EKLENDI and d.get("sayfa") == "/cfo"
                                          for d in dosyalar):
        dispatch, mesaj = await _analizi_baslat(hedef_finansal.id)
        belge_sayisi = sum(1 for d in dosyalar if d.get("durum") == EKLENDI and d.get("sayfa") == "/cfo")
        for d in dosyalar:
            if d.get("durum") == EKLENDI and d.get("sayfa") == "/cfo":
                d["dispatch"] = dispatch
                d["mesaj"] = (mesaj if belge_sayisi == 1 else
                              f"{belge_sayisi} belge tek analizde birleştirildi. {mesaj}")
    # The analysis this request belongs to: the one its financial documents
    # opened or were added to, else the job the domain files attached to.
    is_id = yeni_is or (hedef_finansal.id if hedef_finansal else None) or (hedef.id if hedef else None)
    return {"job_id": is_id, "dosyalar": dosyalar}


def islemler_csv(islemler: list[dict[str, Any]]) -> bytes:
    """Connector transactions as a statement the ingestion reads: signed amounts, ISO dates."""
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(["tarih", "açıklama", "tutar", "tip"])
    for t in islemler:
        kurus = t.get("amount_cents")
        tutar = abs(int(kurus)) / 100 if kurus is not None else abs(float(t.get("amount") or 0))
        tip = "income" if str(t.get("type") or t.get("tx_type") or "").lower() in ("income", "gelir") else "expense"
        tarih = t.get("date") or t.get("transaction_date") or ""
        tarih = tarih.isoformat() if hasattr(tarih, "isoformat") else str(tarih)
        w.writerow([tarih[:10], (t.get("description") or "")[:500], -tutar if tip == "expense" else tutar, tip])
    return out.getvalue().encode("utf-8")


async def islemleri_ekle(
    db: AsyncSession, sahip: Sahip, islemler: list[dict[str, Any]], kaynak: str,
) -> dict[str, Any]:
    """A connector's pull becomes an ordinary analysis the pages can show."""
    ad = f"{kaynak}_{datetime.now(UTC):%Y%m%d_%H%M}.csv"
    return await dosyalari_ekle(db, sahip, [(ad, islemler_csv(islemler))], {ad: S.BANKA_EKSTRESI})
