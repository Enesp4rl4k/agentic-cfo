"""
Muhasebe API — MUHASEBE-5

Endpoint'ler:
  POST /muhasebe/analiz        — İşlemleri THP + double-entry ile analiz et
  GET  /muhasebe/onay-kuyrugu  — SMMM onay bekleyen kayıtları listele
  POST /muhasebe/onayla/{id}   — Kaydı onayla
  POST /muhasebe/duzelt/{id}   — Kaydı düzelt (hesap kodu değiştir)
  POST /muhasebe/reddet/{id}   — Kaydı reddet
  GET  /muhasebe/mizan/{job_id}— Job için mizan özeti
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user, require_role
from app.api.deps_regional import require_tr_pack
from app.database import get_db
from app.models.analysis_job import AnalysisJob
from app.models.transaction import Transaction
from app.models.smmm_onay import SMMMOnayKaydi, OnayDurumu
from app.models.user import User

router = APIRouter(dependencies=[Depends(require_tr_pack)])
logger = logging.getLogger(__name__)


# ── Pydantic şemaları ─────────────────────────────────────────────────────────

class MuhasebeAnalizRequest(BaseModel):
    job_id: str
    company_name: str | None = None
    donem: str | None = Field(None, description="Dönem (ör. '2024-01')")
    use_llm_fallback: bool = True


class OnayRequest(BaseModel):
    onay_notu: str | None = None


class DuzeltiRequest(BaseModel):
    yeni_hesap_kodu: str = Field(..., description="THP hesap kodu (ör. '770')")
    yeni_hesap_adi: str
    duzeltme_aciklama: str | None = None


class ReddetRequest(BaseModel):
    red_neden: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/muhasebe/analiz", status_code=status.HTTP_201_CREATED)
async def muhasebe_analiz(
    body: MuhasebeAnalizRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Bir analiz job'unun işlemlerini THP sınıflandır ve yevmiye kaydı oluştur.
    SMMM onayı gereken kayıtları otomatik olarak onay kuyruğuna ekle.
    """
    from app.agents.accounting.orchestrator import get_muhasebe_agent

    # Job kontrolü
    job = await db.get(AnalysisJob, body.job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Analiz iş kaydı bulunamadı.")
    if job.org_id and job.org_id != current_user.org_id and current_user.role not in ("admin", "owner"):
        raise HTTPException(status_code=403, detail="Bu işe erişim yetkiniz yok.")

    # İşlemleri yükle
    tx_result = await db.execute(
        select(Transaction).where(Transaction.job_id == body.job_id)
    )
    txs = tx_result.scalars().all()

    if not txs:
        raise HTTPException(
            status_code=400,
            detail="Bu job'a ait işlem bulunamadı. Önce analiz çalıştırın.",
        )

    tx_dicts = [
        {
            "id":               tx.id,
            "amount_kurus":     tx.amount_kurus,
            "type":             tx.type,
            "description":      tx.description,
            "vendor":           tx.vendor,
            "transaction_date": tx.transaction_date.isoformat() if tx.transaction_date else None,
        }
        for tx in txs
    ]

    # Muhasebe analizi çalıştır
    agent = get_muhasebe_agent(use_llm_fallback=body.use_llm_fallback)
    sonuc = await agent.run(
        job_id=body.job_id,
        transactions=tx_dicts,
        company_name=body.company_name,
        donem=body.donem,
    )

    # SMMM onay kuyruğuna ekle
    onay_eklendi = 0
    for onay_item in sonuc.onay_kuyrugu:
        kayit = SMMMOnayKaydi(
            job_id=body.job_id,
            org_id=str(job.org_id) if job.org_id else None,
            created_by_user_id=current_user.id,
            kayit_id=onay_item["kayit_id"],
            orijinal_kayit=onay_item,
            durum=OnayDurumu.BEKLIYOR,
            otomatik_hesap_kodu=onay_item.get("thp_hesap_kodu"),
            otomatik_confidence=onay_item.get("confidence"),
            onay_neden=onay_item.get("onay_neden"),
            tx_description=onay_item.get("tx_description"),
            tx_amount_try=onay_item.get("tx_amount_try"),
        )
        db.add(kayit)
        onay_eklendi += 1

    await db.commit()

    result_dict = sonuc.to_dict()
    result_dict["onay_kuyruguna_eklendi"] = onay_eklendi

    logger.info(
        "Muhasebe analizi tamamlandı: job=%s kayıt=%d onay=%d",
        body.job_id, sonuc.kayit_sayisi, onay_eklendi,
    )

    return {"data": result_dict, "error": None}


@router.get("/muhasebe/onay-kuyrugu")
async def onay_kuyrugu_listele(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    durum: str = "bekliyor",
) -> dict[str, Any]:
    """SMMM onay bekleyen kayıtları listele."""
    query = select(SMMMOnayKaydi).where(
        SMMMOnayKaydi.durum == durum,
    )
    if current_user.org_id:
        query = query.where(SMMMOnayKaydi.org_id == str(current_user.org_id))

    result = await db.execute(query.order_by(SMMMOnayKaydi.created_at.desc()).limit(100))
    kayitlar = result.scalars().all()

    return {
        "data": [
            {
                "id":                   k.id,
                "job_id":               k.job_id,
                "kayit_id":             k.kayit_id,
                "durum":                k.durum,
                "tx_description":       k.tx_description,
                "tx_amount_try":        float(k.tx_amount_try) if k.tx_amount_try else None,
                "otomatik_hesap_kodu":  k.otomatik_hesap_kodu,
                "otomatik_confidence":  float(k.otomatik_confidence) if k.otomatik_confidence else None,
                "onay_neden":           k.onay_neden,
                "created_at":          k.created_at.isoformat(),
            }
            for k in kayitlar
        ],
        "error": None,
    }


@router.post("/muhasebe/onayla/{onay_id}")
async def onayla(
    onay_id: str,
    body: OnayRequest,
    current_user: User = Depends(require_role("admin", "owner", "cfo")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """SMMM: Kaydı onayla."""
    kayit = await db.get(SMMMOnayKaydi, onay_id)
    if not kayit:
        raise HTTPException(status_code=404, detail="Onay kaydı bulunamadı.")
    if kayit.durum != OnayDurumu.BEKLIYOR:
        raise HTTPException(status_code=409, detail=f"Kayıt zaten '{kayit.durum}' durumunda.")

    kayit.durum = OnayDurumu.ONAYLANDI
    kayit.onaylayan_user_id = current_user.id
    kayit.onay_zamani = datetime.now(timezone.utc)
    kayit.onay_notu = body.onay_notu
    await db.commit()

    logger.info("SMMM onay: id=%s user=%s", onay_id, current_user.email)
    return {"data": {"onaylandi": True, "kayit_id": onay_id}, "error": None}


@router.post("/muhasebe/duzelt/{onay_id}")
async def duzelt(
    onay_id: str,
    body: DuzeltiRequest,
    current_user: User = Depends(require_role("admin", "owner", "cfo")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """SMMM: Hesap kodunu düzelt ve onayla."""
    kayit = await db.get(SMMMOnayKaydi, onay_id)
    if not kayit:
        raise HTTPException(status_code=404, detail="Onay kaydı bulunamadı.")

    kayit.durum = OnayDurumu.DUZELTILDI
    kayit.onaylayan_user_id = current_user.id
    kayit.onay_zamani = datetime.now(timezone.utc)
    kayit.duzeltilmis_hesap_kodu = body.yeni_hesap_kodu
    kayit.duzeltilmis_hesap_adi = body.yeni_hesap_adi
    kayit.duzeltme_aciklama = body.duzeltme_aciklama
    await db.commit()

    logger.info(
        "SMMM düzeltme: id=%s %s→%s user=%s",
        onay_id, kayit.otomatik_hesap_kodu, body.yeni_hesap_kodu, current_user.email,
    )
    return {
        "data": {
            "duzeltildi":        True,
            "eski_hesap_kodu":   kayit.otomatik_hesap_kodu,
            "yeni_hesap_kodu":   body.yeni_hesap_kodu,
        },
        "error": None,
    }


@router.post("/muhasebe/reddet/{onay_id}")
async def reddet(
    onay_id: str,
    body: ReddetRequest,
    current_user: User = Depends(require_role("admin", "owner", "cfo")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """SMMM: Kaydı reddet."""
    kayit = await db.get(SMMMOnayKaydi, onay_id)
    if not kayit:
        raise HTTPException(status_code=404, detail="Onay kaydı bulunamadı.")

    kayit.durum = OnayDurumu.REDDEDILDI
    kayit.onaylayan_user_id = current_user.id
    kayit.onay_zamani = datetime.now(timezone.utc)
    kayit.onay_notu = body.red_neden
    await db.commit()

    logger.info("SMMM red: id=%s user=%s neden=%s", onay_id, current_user.email, body.red_neden)
    return {"data": {"reddedildi": True, "kayit_id": onay_id}, "error": None}


@router.get("/muhasebe/mizan/{job_id}")
async def mizan_ozet(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Bir job için onaylanmış muhasebe kayıtlarından mizan özeti.
    Sadece onaylanmış veya düzeltilmiş kayıtları içerir.
    """
    result = await db.execute(
        select(SMMMOnayKaydi).where(
            SMMMOnayKaydi.job_id == job_id,
            SMMMOnayKaydi.durum.in_([OnayDurumu.ONAYLANDI, OnayDurumu.DUZELTILDI]),
        )
    )
    kayitlar = result.scalars().all()

    if not kayitlar:
        return {
            "data": {
                "job_id":   job_id,
                "mesaj":    "Onaylanmış muhasebe kaydı bulunamadı.",
                "mizan":    {},
                "toplam":   {"borc": 0, "alacak": 0},
            },
            "error": None,
        }

    # Mizan hesapla
    mizan: dict[str, dict[str, Any]] = {}
    for k in kayitlar:
        kayit_data = k.orijinal_kayit or {}
        # Düzeltme yapıldıysa hesap kodunu güncelle
        for satir in kayit_data.get("satirlar", []):
            kod = k.duzeltilmis_hesap_kodu or satir["hesap_kodu"]
            adi = k.duzeltilmis_hesap_adi or satir["hesap_adi"]
            if kod not in mizan:
                mizan[kod] = {"hesap_adi": adi, "borc": 0, "alacak": 0}
            mizan[kod]["borc"]   += satir.get("borc", 0)
            mizan[kod]["alacak"] += satir.get("alacak", 0)

    for h in mizan.values():
        h["bakiye"] = h["borc"] - h["alacak"]

    toplam_borc   = sum(h["borc"]   for h in mizan.values())
    toplam_alacak = sum(h["alacak"] for h in mizan.values())

    return {
        "data": {
            "job_id":        job_id,
            "kayit_sayisi":  len(kayitlar),
            "mizan":         mizan,
            "toplam": {
                "borc":    toplam_borc,
                "alacak":  toplam_alacak,
                "dengeli": toplam_borc == toplam_alacak,
            },
        },
        "error": None,
    }
