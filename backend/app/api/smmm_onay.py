"""
SMMM Onay Workflow API — MUHASEBE-4

Agent hazırlar → SMMM görür → tek tıkla onaylar / düzeltir / reddeder.

Endpoints:
  GET  /smmm/onay/queue          → Bekleyen onay listesi
  GET  /smmm/onay/queue/{job_id} → Belirli iş için bekleyen onaylar
  GET  /smmm/onay/package/{job_id} → SMMM paket özeti (review/failed/canonical)
  POST /smmm/onay/{kayit_id}/onayla   → Onayla
  POST /smmm/onay/{kayit_id}/duzeltle → Hesap kodunu düzelterek onayla
  POST /smmm/onay/{kayit_id}/reddet   → Reddet
  GET  /smmm/onay/stats          → Onay istatistikleri
  POST /smmm/onay/toplu-onayla   → Birden fazla kaydı toplu onayla
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.api.deps_regional import require_tr_pack
from app.database import get_db
from app.models.smmm_onay import OnayDurumu, SMMMOnayKaydi
from app.models.user import User

router = APIRouter(dependencies=[Depends(require_tr_pack)])
logger = logging.getLogger(__name__)


def _user_id(user: User) -> str:
    return str(user.id)


# ── Request schemas ──────────────────────────────────────────────────────────

class OnaylaRequest(BaseModel):
    onay_notu: str | None = Field(None, description="Opsiyonel onay notu")


class DuzelRequest(BaseModel):
    hesap_kodu:  str = Field(..., description="Yeni hesap kodu (örn: 320)")
    hesap_adi:   str = Field(..., description="Yeni hesap adı")
    aciklama:    str | None = Field(None, description="Düzeltme gerekçesi")


class ReddetRequest(BaseModel):
    neden: str = Field(..., description="Red gerekçesi (zorunlu)")


class TopluOnayRequest(BaseModel):
    kayit_idler: list[str] = Field(..., description="Onaylanacak kayıt ID'leri")
    onay_notu:   str | None = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _kayit_to_dict(k: SMMMOnayKaydi) -> dict[str, Any]:
    return {
        "id":                    k.id,
        "job_id":                k.job_id,
        "org_id":                k.org_id,
        "kayit_id":              k.kayit_id,
        "durum":                 k.durum,
        "tx_description":        k.tx_description,
        "tx_amount_try":         float(k.tx_amount_try) if k.tx_amount_try else None,
        "tx_tarih":              k.tx_tarih.isoformat() if k.tx_tarih else None,
        "otomatik_hesap_kodu":   k.otomatik_hesap_kodu,
        "otomatik_confidence":   float(k.otomatik_confidence) if k.otomatik_confidence else None,
        "otomatik_yontem":       k.otomatik_yontem,
        "onay_neden":            k.onay_neden,
        "orijinal_kayit":        k.orijinal_kayit,
        "duzeltilmis_hesap_kodu": k.duzeltilmis_hesap_kodu,
        "duzeltilmis_hesap_adi": k.duzeltilmis_hesap_adi,
        "duzeltme_aciklama":     k.duzeltme_aciklama,
        "onaylayan_user_id":     k.onaylayan_user_id,
        "onay_zamani":           k.onay_zamani.isoformat() if k.onay_zamani else None,
        "onay_notu":             k.onay_notu,
        "created_at":            k.created_at.isoformat(),
        "updated_at":            k.updated_at.isoformat(),
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/smmm/onay/queue")
async def get_onay_queue(
    durum:        str = "bekliyor",
    limit:        int = 50,
    offset:       int = 0,
    current_user: User = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Bekleyen (veya belirli durumdaki) onay kuyruğunu listele.

    Parametreler:
      durum: bekliyor | onaylandi | duzeltildi | reddedildi | all
      limit: sayfa boyutu
      offset: sayfa offseti
    """
    org_id = getattr(current_user, "org_id", None) or getattr(current_user, "organization_id", None)

    query = select(SMMMOnayKaydi).order_by(SMMMOnayKaydi.created_at.desc())

    if durum != "all":
        query = query.where(SMMMOnayKaydi.durum == durum)

    if org_id:
        query = query.where(SMMMOnayKaydi.org_id == str(org_id))

    total_q = select(func.count()).select_from(query.subquery())
    total_res = await db.execute(total_q)
    total = total_res.scalar_one()

    result = await db.execute(query.limit(limit).offset(offset))
    kayitlar = result.scalars().all()

    return {
        "data": {
            "total":   total,
            "limit":   limit,
            "offset":  offset,
            "durum":   durum,
            "kayitlar": [_kayit_to_dict(k) for k in kayitlar],
        },
        "error": None,
    }


@router.get("/smmm/onay/queue/{job_id}")
async def get_onay_queue_for_job(
    job_id:       str,
    current_user: User = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Belirli bir analiz işi için bekleyen onayları listele."""
    result = await db.execute(
        select(SMMMOnayKaydi)
        .where(and_(
            SMMMOnayKaydi.job_id == job_id,
            SMMMOnayKaydi.durum == OnayDurumu.BEKLIYOR,
        ))
        .order_by(SMMMOnayKaydi.tx_amount_try.desc())  # Yüksek tutarlı önce
    )
    kayitlar = result.scalars().all()

    return {
        "data": {
            "job_id":    job_id,
            "bekleyen":  len(kayitlar),
            "kayitlar":  [_kayit_to_dict(k) for k in kayitlar],
        },
        "error": None,
    }


@router.post("/smmm/onay/{kayit_id}/onayla")
async def onayla(
    kayit_id:     str,
    req:          OnaylaRequest,
    current_user: User = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Kaydı onayla — hesap kodu değişmez, sadece onay damgası."""
    kayit = await db.get(SMMMOnayKaydi, kayit_id)
    if not kayit:
        raise HTTPException(status_code=404, detail="Onay kaydı bulunamadı")
    if kayit.durum != OnayDurumu.BEKLIYOR:
        raise HTTPException(status_code=409, detail=f"Kayıt zaten işlendi: {kayit.durum}")

    kayit.durum            = OnayDurumu.ONAYLANDI
    kayit.onaylayan_user_id = _user_id(current_user)
    kayit.onay_zamani      = datetime.now(UTC)
    kayit.onay_notu        = req.onay_notu
    kayit.updated_at       = datetime.now(UTC)

    await db.commit()
    logger.info("SMMM onay: kayit=%s user=%s", kayit_id, _user_id(current_user))

    return {"data": _kayit_to_dict(kayit), "error": None}


@router.post("/smmm/onay/{kayit_id}/duzeltle")
async def duzeltle(
    kayit_id:     str,
    req:          DuzelRequest,
    current_user: User = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Hesap kodunu düzelterek onayla. Orijinal otomatik sınıflandırma korunur."""
    kayit = await db.get(SMMMOnayKaydi, kayit_id)
    if not kayit:
        raise HTTPException(status_code=404, detail="Onay kaydı bulunamadı")
    if kayit.durum != OnayDurumu.BEKLIYOR:
        raise HTTPException(status_code=409, detail=f"Kayıt zaten işlendi: {kayit.durum}")

    kayit.durum                  = OnayDurumu.DUZELTILDI
    kayit.onaylayan_user_id      = _user_id(current_user)
    kayit.onay_zamani            = datetime.now(UTC)
    kayit.duzeltilmis_hesap_kodu = req.hesap_kodu
    kayit.duzeltilmis_hesap_adi  = req.hesap_adi
    kayit.duzeltme_aciklama      = req.aciklama
    kayit.updated_at             = datetime.now(UTC)

    await db.commit()
    logger.info(
        "SMMM düzeltme: kayit=%s user=%s yeni_hesap=%s",
        kayit_id, _user_id(current_user), req.hesap_kodu
    )

    return {"data": _kayit_to_dict(kayit), "error": None}


@router.post("/smmm/onay/{kayit_id}/reddet")
async def reddet(
    kayit_id:     str,
    req:          ReddetRequest,
    current_user: User = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Kaydı reddet. Gerekçe zorunlu."""
    kayit = await db.get(SMMMOnayKaydi, kayit_id)
    if not kayit:
        raise HTTPException(status_code=404, detail="Onay kaydı bulunamadı")
    if kayit.durum != OnayDurumu.BEKLIYOR:
        raise HTTPException(status_code=409, detail=f"Kayıt zaten işlendi: {kayit.durum}")

    kayit.durum            = OnayDurumu.REDDEDILDI
    kayit.onaylayan_user_id = _user_id(current_user)
    kayit.onay_zamani      = datetime.now(UTC)
    kayit.onay_notu        = req.neden
    kayit.updated_at       = datetime.now(UTC)

    await db.commit()
    logger.info("SMMM red: kayit=%s user=%s neden=%s", kayit_id, _user_id(current_user), req.neden)

    return {"data": _kayit_to_dict(kayit), "error": None}


@router.post("/smmm/onay/toplu-onayla")
async def toplu_onayla(
    req:          TopluOnayRequest,
    current_user: User = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Birden fazla bekleyen kaydı tek seferde onayla (düşük riskli toplu işlem)."""
    if not req.kayit_idler:
        raise HTTPException(status_code=400, detail="En az 1 kayıt ID'si gerekli")
    if len(req.kayit_idler) > 100:
        raise HTTPException(status_code=400, detail="Toplu onay en fazla 100 kayıt destekler")

    result = await db.execute(
        select(SMMMOnayKaydi).where(
            and_(
                SMMMOnayKaydi.id.in_(req.kayit_idler),
                SMMMOnayKaydi.durum == OnayDurumu.BEKLIYOR,
            )
        )
    )
    kayitlar = result.scalars().all()

    now = datetime.now(UTC)
    approved_ids = []
    for kayit in kayitlar:
        kayit.durum             = OnayDurumu.ONAYLANDI
        kayit.onaylayan_user_id = _user_id(current_user)
        kayit.onay_zamani       = now
        kayit.onay_notu         = req.onay_notu
        kayit.updated_at        = now
        approved_ids.append(kayit.id)

    await db.commit()
    logger.info("SMMM toplu onay: %d kayit, user=%s", len(approved_ids), _user_id(current_user))

    return {
        "data": {
            "onaylandi_count": len(approved_ids),
            "onaylandi_ids":   approved_ids,
            "requested":       len(req.kayit_idler),
            "skipped":         len(req.kayit_idler) - len(approved_ids),
        },
        "error": None,
    }


@router.get("/smmm/onay/package/{job_id}")
async def get_onay_package(
    job_id:       str,
    current_user: User = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    SMMM onay paketi özeti: awaiting_review + failed + canonical count.

    Paraşüt → canonical → CFO hattı için muhasebeci paket görünümü.
    """
    from app.models.analysis_job import AnalysisJob
    from app.models.canonical_transaction import CanonicalTransaction

    org_id = getattr(current_user, "org_id", None) or getattr(
        current_user, "organization_id", None
    )

    job = await db.get(AnalysisJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Analiz işi bulunamadı")
    if org_id and str(job.org_id) != str(org_id):
        raise HTTPException(status_code=403, detail="Bu işe erişim yok")

    bekleyen_q = select(func.count()).where(
        and_(
            SMMMOnayKaydi.job_id == job_id,
            SMMMOnayKaydi.durum == OnayDurumu.BEKLIYOR,
        )
    )
    reddedilen_q = select(func.count()).where(
        and_(
            SMMMOnayKaydi.job_id == job_id,
            SMMMOnayKaydi.durum == OnayDurumu.REDDEDILDI,
        )
    )
    bekleyen = int((await db.execute(bekleyen_q)).scalar_one() or 0)
    reddedilen = int((await db.execute(reddedilen_q)).scalar_one() or 0)

    sync_run_id = None
    meta = job.result_metadata if isinstance(job.result_metadata, dict) else {}
    sync_run_id = meta.get("sync_run_id")

    canonical_count = 0
    try:
        cq = select(func.count()).select_from(CanonicalTransaction).where(
            CanonicalTransaction.org_id == str(job.org_id)
        )
        if sync_run_id:
            cq = cq.where(CanonicalTransaction.sync_run_id == str(sync_run_id))
        canonical_count = int((await db.execute(cq)).scalar_one() or 0)
    except Exception:
        canonical_count = 0

    awaiting_review = bool(job.awaiting_review) or str(job.status) == "awaiting_review"
    failed = str(job.status) == "failed"

    return {
        "data": {
            "job_id": job_id,
            "org_id": str(job.org_id),
            "job_status": str(job.status),
            "awaiting_review": awaiting_review,
            "failed": failed,
            "error_message": job.error_message if failed else None,
            "smmm": {
                "bekliyor": bekleyen,
                "reddedildi": reddedilen,
            },
            "canonical_count": canonical_count,
            "sync_run_id": sync_run_id,
            "quality_score": meta.get("quality_score"),
            "sync_fingerprint": meta.get("sync_fingerprint"),
            "ready_for_export": (
                not failed
                and bekleyen == 0
                and not awaiting_review
                and canonical_count > 0
            ),
        },
        "error": None,
    }


@router.get("/smmm/onay/stats")
async def onay_stats(
    current_user: User = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Onay kuyruğu istatistikleri."""
    org_id = getattr(current_user, "org_id", None) or getattr(current_user, "organization_id", None)

    counts: dict[str, int] = {}
    for durum in [OnayDurumu.BEKLIYOR, OnayDurumu.ONAYLANDI, OnayDurumu.DUZELTILDI, OnayDurumu.REDDEDILDI]:
        q = select(func.count()).where(SMMMOnayKaydi.durum == durum)
        if org_id:
            q = q.where(SMMMOnayKaydi.org_id == str(org_id))
        res = await db.execute(q)
        counts[durum] = res.scalar_one()

    # Average confidence of pending items
    avg_conf_q = select(func.avg(SMMMOnayKaydi.otomatik_confidence)).where(
        SMMMOnayKaydi.durum == OnayDurumu.BEKLIYOR
    )
    if org_id:
        avg_conf_q = avg_conf_q.where(SMMMOnayKaydi.org_id == str(org_id))
    avg_conf_res = await db.execute(avg_conf_q)
    avg_confidence = avg_conf_res.scalar_one()

    return {
        "data": {
            "bekliyor":         counts[OnayDurumu.BEKLIYOR],
            "onaylandi":        counts[OnayDurumu.ONAYLANDI],
            "duzeltildi":       counts[OnayDurumu.DUZELTILDI],
            "reddedildi":       counts[OnayDurumu.REDDEDILDI],
            "toplam":           sum(counts.values()),
            "avg_confidence":   round(float(avg_confidence), 3) if avg_confidence else None,
            "onay_orani":       round(
                (counts[OnayDurumu.ONAYLANDI] + counts[OnayDurumu.DUZELTILDI]) /
                max(1, sum(counts.values()) - counts[OnayDurumu.BEKLIYOR]),
                3
            ),
        },
        "error": None,
    }
