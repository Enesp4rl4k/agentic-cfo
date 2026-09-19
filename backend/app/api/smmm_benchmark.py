"""
SMMM Portal + Benchmark Intelligence API

SMMM (muhasebeci) endpoint'leri:
  POST /smmm/register              -- Muhasebeci kaydı
  GET  /smmm/profile               -- Kendi profili
  GET  /smmm/clients               -- Müşteri listesi
  POST /smmm/clients               -- Yeni müşteri ekle
  PUT  /smmm/clients/{id}          -- Müşteri güncelle
  DELETE /smmm/clients/{id}        -- Müşteri sil
  DELETE /smmm/clients/{id}        -- Müşteriyi pasife al (kayıt silinmez)

  Bir müşteri için analiz ayrı bir uç değildir: POST /upload dosyayı
  `client_id` ile alır ve zincir oradan yürür. Burada bir /analyze ucu
  ilan ediliyordu ama hiç yazılmamıştı.
  GET  /smmm/dashboard             -- Tüm müşterilerin özet durumu

Benchmark endpoint'leri:
  POST /benchmark/compare          -- C-Suite verileriyle benchmark
  POST /benchmark/from-org         -- CompanyContext'ten benchmark
  GET  /benchmark/sectors          -- Desteklenen sektörler
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.access import current_user_org_matches
from app.api.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.services.smmm_clients import status_for_clients

router = APIRouter()
logger = logging.getLogger(__name__)


def _get_user_id(user: User) -> str:
    return str(user.id)


# ── SMMM Schemas ──────────────────────────────────────────────────────────────

class SMMMMuhasebeciRegister(BaseModel):
    unvan:     str | None = None
    vergi_no:  str | None = None
    oda_no:    str | None = None
    firma_adi: str | None = None
    il:        str | None = None
    telefon:   str | None = None


class SMMMMusteriCreate(BaseModel):
    firma_adi: str
    vergi_no:  str | None = None
    sektor:    str | None = "saas"
    buyukluk:  str | None = "smb"
    il:        str | None = None
    notlar:    str | None = None


class SMMMMusteriUpdate(BaseModel):
    firma_adi: str | None = None
    vergi_no:  str | None = None
    sektor:    str | None = None
    buyukluk:  str | None = None
    notlar:    str | None = None
    is_active: bool | None = None


# ── SMMM Endpoints ─────────────────────────────────────────────────────────────

@router.post("/smmm/register")
async def smmm_register(
    req:          SMMMMuhasebeciRegister,
    current_user: User = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Muhasebeci olarak platforma kayıt ol."""
    from app.models.smmm_portal import SMMMMuhasebeci

    user_id = _get_user_id(current_user)

    # Zaten kayıtlı mı?
    stmt     = select(SMMMMuhasebeci).where(SMMMMuhasebeci.user_id == user_id)
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing:
        return {"data": {"already_registered": True, **existing.to_dict()}, "error": None}

    muhasebeci = SMMMMuhasebeci(
        user_id   = user_id,
        unvan     = req.unvan,
        vergi_no  = req.vergi_no,
        oda_no    = req.oda_no,
        firma_adi = req.firma_adi,
        il        = req.il,
        telefon   = req.telefon,
    )
    db.add(muhasebeci)
    await db.commit()
    await db.refresh(muhasebeci)
    return {"data": {"already_registered": False, **muhasebeci.to_dict()}, "error": None}


@router.get("/smmm/profile")
async def smmm_profile(
    current_user: User = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Muhasebeci profili ve istatistikler."""
    from app.models.smmm_portal import SMMMMuhasebeci, SMMMMusteriKayit

    user_id = _get_user_id(current_user)
    stmt    = select(SMMMMuhasebeci).where(SMMMMuhasebeci.user_id == user_id)
    m       = (await db.execute(stmt)).scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="SMMM kaydı bulunamadı. Önce /smmm/register yapın.")

    # Aktif müşteri sayısı
    count_stmt = select(SMMMMusteriKayit).where(
        SMMMMusteriKayit.muhasebeci_id == m.id,
        SMMMMusteriKayit.is_active.is_(True),
    )
    clients = (await db.execute(count_stmt)).scalars().all()

    return {
        "ok": True,
        "profile": m.to_dict(),
        "stats": {
            "active_clients":    len(clients),
            "max_clients":       m.max_clients,
            "capacity_pct":      round(len(clients) / m.max_clients * 100, 1),
            "analyzed_recently": sum(1 for c in clients if c.last_analysis_at),
        },
    }


@router.get("/smmm/clients")
async def smmm_list_clients(
    current_user: User = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Muhasebecinin tüm aktif müşterileri."""
    from app.models.smmm_portal import SMMMMuhasebeci, SMMMMusteriKayit

    user_id = _get_user_id(current_user)
    stmt    = select(SMMMMuhasebeci).where(SMMMMuhasebeci.user_id == user_id)
    m       = (await db.execute(stmt)).scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="SMMM kaydı bulunamadı")

    clients_stmt = (
        select(SMMMMusteriKayit)
        .where(SMMMMusteriKayit.muhasebeci_id == m.id)
        .order_by(desc(SMMMMusteriKayit.updated_at))
    )
    clients = (await db.execute(clients_stmt)).scalars().all()
    statuses = await status_for_clients(db, [str(c.id) for c in clients])

    return {
        "ok":      True,
        "clients": [
            {**c.to_dict(), "durum": statuses[str(c.id)].to_dict()} for c in clients
        ],
        "count":   len(clients),
    }


@router.post("/smmm/clients")
async def smmm_add_client(
    req:          SMMMMusteriCreate,
    current_user: User = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Yeni müşteri firma ekle."""
    from app.models.smmm_portal import SMMMMuhasebeci, SMMMMusteriKayit

    user_id = _get_user_id(current_user)
    stmt    = select(SMMMMuhasebeci).where(SMMMMuhasebeci.user_id == user_id)
    m       = (await db.execute(stmt)).scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="SMMM kaydı bulunamadı")

    # Plan limiti
    count_stmt = select(SMMMMusteriKayit).where(
        SMMMMusteriKayit.muhasebeci_id == m.id,
        SMMMMusteriKayit.is_active.is_(True),
    )
    existing_count = len((await db.execute(count_stmt)).scalars().all())
    if existing_count >= m.max_clients:
        raise HTTPException(
            status_code=402,
            detail=f"Plan limitine ulaşıldı ({m.max_clients} müşteri). Pro plana geçin."
        )

    client = SMMMMusteriKayit(
        muhasebeci_id = m.id,
        firma_adi     = req.firma_adi,
        vergi_no      = req.vergi_no,
        sektor        = req.sektor,
        buyukluk      = req.buyukluk,
        il            = req.il,
        notlar        = req.notlar,
    )
    db.add(client)
    await db.commit()
    await db.refresh(client)
    return {"data": {"client": client.to_dict()}, "error": None}


@router.put("/smmm/clients/{client_id}")
async def smmm_update_client(
    client_id:    str,
    req:          SMMMMusteriUpdate,
    current_user: User = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Müşteri bilgilerini güncelle."""
    from app.models.smmm_portal import SMMMMuhasebeci, SMMMMusteriKayit

    user_id = _get_user_id(current_user)
    m_stmt  = select(SMMMMuhasebeci).where(SMMMMuhasebeci.user_id == user_id)
    m       = (await db.execute(m_stmt)).scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="SMMM kaydı bulunamadı")

    c_stmt = select(SMMMMusteriKayit).where(
        SMMMMusteriKayit.id == client_id,
        SMMMMusteriKayit.muhasebeci_id == m.id,
    )
    client = (await db.execute(c_stmt)).scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="Müşteri bulunamadı")

    for field_name, value in req.model_dump(exclude_none=True).items():
        setattr(client, field_name, value)
    await db.commit()
    return {"data": {"client": client.to_dict()}, "error": None}


@router.delete("/smmm/clients/{client_id}")
async def smmm_deactivate_client(
    client_id:    str,
    current_user: User = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Müşteriyi listeden çıkar — kaydı silmeden.

    Deactivated rather than deleted: the client's jobs, approved entries and
    sealed packets stay explainable, and a sealed period must remain readable
    after the engagement ends. The same rule the related-party register follows.

    The portal page has been calling this since it was written; the route did
    not exist, so the button answered 404 and the row stayed on screen.
    """
    from app.models.smmm_portal import SMMMMuhasebeci, SMMMMusteriKayit

    user_id = _get_user_id(current_user)
    m = (
        await db.execute(
            select(SMMMMuhasebeci).where(SMMMMuhasebeci.user_id == user_id)
        )
    ).scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="SMMM kaydı bulunamadı")

    client = (
        await db.execute(
            select(SMMMMusteriKayit).where(
                SMMMMusteriKayit.id == client_id,
                SMMMMusteriKayit.muhasebeci_id == m.id,
            )
        )
    ).scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="Müşteri bulunamadı")

    client.is_active = False
    await db.commit()
    return {"data": {"id": client.id, "is_active": False}, "error": None}


@router.get("/smmm/dashboard")
async def smmm_dashboard(
    current_user: User = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Tüm müşterilerin özet durumu — muhasebeci ana sayfası."""
    from app.models.smmm_portal import SMMMMuhasebeci, SMMMMusteriKayit

    user_id = _get_user_id(current_user)
    m_stmt  = select(SMMMMuhasebeci).where(SMMMMuhasebeci.user_id == user_id)
    m       = (await db.execute(m_stmt)).scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="SMMM kaydı bulunamadı")

    clients_stmt = (
        select(SMMMMusteriKayit)
        .where(SMMMMusteriKayit.muhasebeci_id == m.id, SMMMMusteriKayit.is_active.is_(True))
    )
    clients = (await db.execute(clients_stmt)).scalars().all()

    # These counts used to come from `health_score` and `health_label` on the
    # client record — fields the model calls a cache and which nothing has ever
    # written, so `analyzed_clients` was always 0 for every accountant who has
    # ever opened this page. They are derived from the jobs now, which cannot
    # go stale.
    statuses = await status_for_clients(db, [str(c.id) for c in clients])
    rows = [{**c.to_dict(), "durum": statuses[str(c.id)].to_dict()} for c in clients]

    analysed = [r for r in rows if r["durum"]["job_count"] > 0]
    # What an accountant actually needs first: whose work is waiting on them.
    attention = [r for r in rows if r["durum"]["needs_attention"]]
    sealed = [r for r in rows if r["durum"]["packet_sealed"]]
    pending_total = sum(r["durum"]["pending_review"] for r in rows)

    return {
        "ok":              True,
        "muhasebeci":      m.to_dict(),
        "summary": {
            "total_clients":     len(clients),
            "analyzed_clients":  len(analysed),
            "needs_attention":   len(attention),
            "sealed_clients":    len(sealed),
            "pending_entries":   pending_total,
        },
        "clients":         rows,
        "attention_list":  attention,
    }


# ── Benchmark Endpoints ────────────────────────────────────────────────────────

class BenchmarkCompareRequest(BaseModel):
    pnl:         dict[str, Any] | None = None
    cashflow:    dict[str, Any] | None = None
    forecast:    dict[str, Any] | None = None
    cmo_data:    dict[str, Any] | None = None
    chro_data:   dict[str, Any] | None = None
    coo_data:    dict[str, Any] | None = None
    cto_data:    dict[str, Any] | None = None
    sector:      str = Field("saas", description="saas|ecommerce|services|retail|smb")
    company_name: str = "Şirket"


class BenchmarkFromOrgRequest(BaseModel):
    org_id:      str
    sector:      str = "saas"
    company_name: str | None = None


@router.post("/benchmark/compare")
async def benchmark_compare(
    req:          BenchmarkCompareRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    C-Suite verileriyle sektör benchmark karşılaştırması.
    Şirketin metriklerini Türkiye sektör ortalamasıyla kıyaslar.
    """
    from app.services.benchmark_intelligence import get_benchmark_service

    svc = get_benchmark_service()
    try:
        report = svc.compare_all(
            pnl          = req.pnl,
            cashflow     = req.cashflow,
            forecast     = req.forecast,
            cmo_data     = req.cmo_data,
            chro_data    = req.chro_data,
            coo_data     = req.coo_data,
            cto_data     = req.cto_data,
            sector       = req.sector,
            company_name = req.company_name,
        )
        return {"data": {"report": report.to_dict()}, "error": None}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/benchmark/from-org")
async def benchmark_from_org(
    req:          BenchmarkFromOrgRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """CompanyContext'teki verilerden benchmark raporu üret."""
    from app.services.benchmark_intelligence import get_benchmark_service
    from app.services.company_context import get_company_context

    try:
        # The organisation came from the request, never compared with the caller's.
        if not current_user_org_matches(current_user, req.org_id):
            raise HTTPException(status_code=404, detail="Kayıt bulunamadı.")
        ctx     = await get_company_context(req.org_id) or {}
        results = ctx.get("agent_results") or {}
        cfo_r   = results.get("cfo") or {}

        svc    = get_benchmark_service()
        report = svc.compare_all(
            pnl          = cfo_r.get("pnl"),
            cashflow     = cfo_r.get("cashflow"),
            forecast     = cfo_r.get("forecast"),
            cmo_data     = results.get("cmo"),
            chro_data    = results.get("chro"),
            coo_data     = results.get("coo"),
            sector       = req.sector,
            company_name = req.company_name or ctx.get("company_name", "Şirket"),
        )
        return {"data": {"report": report.to_dict()}, "error": None}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/benchmark/sectors")
async def benchmark_sectors(
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Desteklenen sektörler ve mevcut benchmark metrikleri."""
    return {
        "sectors": [
            {"id": "saas",      "label": "SaaS / Yazılım",      "metric_count": 12},
            {"id": "ecommerce", "label": "E-ticaret",            "metric_count": 8},
            {"id": "services",  "label": "Hizmet Sektörü",       "metric_count": 7},
            {"id": "smb",       "label": "Genel KOBİ (Türkiye)", "metric_count": 6},
        ],
        "available_metrics": [
            "Net Kâr Marjı", "Brüt Kâr Marjı", "Gelir Büyümesi", "Nakit Ömrü",
            "ROAS", "Aylık Churn", "LTV/CAC", "Personel Devir Hızı",
            "Çalışan Bağlılığı", "SLA Uyumu", "Altyapı İsraf Oranı",
        ],
    }
