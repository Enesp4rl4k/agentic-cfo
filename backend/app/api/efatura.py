"""
GİB e-Fatura API endpoints.

POST /api/v1/efatura/sync
     e-Fatura gelen/giden listesini çek → CFO job oluştur → analiz başlat.

GET  /api/v1/efatura/tax-calendar/{period}
     Belirli bir dönem için vergi takvimi (KDV, geçici vergi) oluştur.

GET  /api/v1/efatura/invoices/{direction}
     Gelen (inbound) veya giden (outbound) fatura listesi.

GET  /api/v1/efatura/status
     GİB bağlantı durumu — credentials yapılandırılmış mı?

SETUP:
  .env dosyasına ekle:
    GIB_VKN=1234567890
    GIB_USERNAME=your_username
    GIB_PASSWORD=your_password
    GIB_SANDBOX=true
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db

router = APIRouter()
logger = logging.getLogger(__name__)


class EFaturaSyncRequest(BaseModel):
    start_date: str  # YYYY-MM-DD
    end_date:   str  # YYYY-MM-DD
    analyze:    bool = True   # Otomatik CFO analizi başlat


@router.get("/efatura/status")
async def get_efatura_status() -> dict[str, Any]:
    """
    GİB e-Fatura bağlantı durumunu kontrol et.
    Credentials .env'de yapılandırılmış mı?
    """
    from app.services.gib_efatura import get_efatura_client
    client = get_efatura_client()

    if client is None:
        return {
            "data": {
                "configured": False,
                "sandbox":    True,
                "message":    (
                    "GİB e-Fatura kimlik bilgileri yapılandırılmamış. "
                    ".env dosyasına GIB_VKN, GIB_USERNAME, GIB_PASSWORD ekleyin."
                ),
                "setup_guide": {
                    "GIB_VKN":      "Vergi Kimlik Numaranız (10 hane)",
                    "GIB_USERNAME": "e-Fatura portal kullanıcı adı",
                    "GIB_PASSWORD": "e-Fatura portal şifresi",
                    "GIB_SANDBOX":  "true (test ortamı) / false (production)",
                },
                "sandbox_url": "https://efatura.gib.gov.tr/test",
            },
            "error": None,
        }

    return {
        "data": {
            "configured": True,
            "sandbox":    client.sandbox,
            "vkn":        client.vkn[:3] + "***" + client.vkn[-2:],  # Masked
            "base_url":   client.base_url,
            "message":    f"{'Test ortamı' if client.sandbox else 'Production ortamı'} yapılandırıldı.",
        },
        "error": None,
    }


@router.get("/efatura/invoices/{direction}")
async def list_invoices(
    direction:  str = "inbound",
    start_date: str = Query(default=None, description="YYYY-MM-DD"),
    end_date:   str = Query(default=None, description="YYYY-MM-DD"),
) -> dict[str, Any]:
    """
    e-Fatura listesi çek.

    direction:
      - inbound  → gelen faturalar (tedarikçilerden, gider)
      - outbound → giden faturalar (müşterilere, gelir)
    """
    if direction not in ("inbound", "outbound"):
        raise HTTPException(
            status_code=400,
            detail="direction 'inbound' veya 'outbound' olmalı.",
        )

    from app.services.gib_efatura import get_efatura_client, GIBError
    client = get_efatura_client()
    if not client:
        raise HTTPException(
            status_code=503,
            detail="GİB e-Fatura yapılandırılmamış. /efatura/status endpoint'ini kontrol edin.",
        )

    # Default: last 30 days
    if not end_date:
        end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if not start_date:
        start_date = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")

    try:
        await client.authenticate()
        if direction == "inbound":
            invoices = await client.get_inbox(start_date, end_date)
        else:
            invoices = await client.get_outbox(start_date, end_date)
    except GIBError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    finally:
        await client.close()

    return {
        "data": {
            "direction":       direction,
            "period":          f"{start_date} – {end_date}",
            "invoice_count":   len(invoices),
            "invoices":        invoices[:50],  # Cap at 50 for API response
            "total_net":       sum(inv.get("net_amount", 0) for inv in invoices),
            "total_vat":       sum(inv.get("vat_amount", 0) for inv in invoices),
            "total_gross":     sum(inv.get("gross_amount", 0) for inv in invoices),
        },
        "error": None,
    }


@router.get("/efatura/tax-calendar/{period}")
async def get_tax_calendar(
    period: str,  # YYYY-MM format
) -> dict[str, Any]:
    """
    Belirli bir dönem için vergi takvimi oluştur.

    period: "2024-01" formatında yıl-ay

    Hesaplanan vergiler:
    - KDV: giden KDV - gelen KDV = ödenecek/iade edilecek
    - Geçici Vergi: dönem kârı × %25 / 4
    - Ödeme tarihleri otomatik hesaplanır
    """
    import re
    if not re.match(r"^\d{4}-\d{2}$", period):
        raise HTTPException(
            status_code=400,
            detail="period 'YYYY-MM' formatında olmalı (örn: '2024-01').",
        )

    from app.services.gib_efatura import get_efatura_client, GIBError, compute_tax_calendar
    client = get_efatura_client()
    if not client:
        raise HTTPException(
            status_code=503,
            detail="GİB e-Fatura yapılandırılmamış.",
        )

    start_date = f"{period}-01"
    year, month = int(period[:4]), int(period[5:7])
    last_day = 31 if month in (1, 3, 5, 7, 8, 10, 12) else 30 if month in (4, 6, 9, 11) else 29 if year % 4 == 0 else 28
    end_date = f"{period}-{last_day:02d}"

    try:
        await client.authenticate()
        invoices = await client.get_all_transactions(start_date, end_date)
    except GIBError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    finally:
        await client.close()

    calendar = compute_tax_calendar(invoices, period)

    return {"data": calendar, "error": None}


@router.post("/efatura/sync")
async def sync_efatura(
    body: EFaturaSyncRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    e-Fatura verilerini senkronize et ve CFO analizi başlat.

    Adımlar:
    1. GİB'den gelen + giden faturaları çek
    2. CFO transaction formatına dönüştür
    3. Yeni AnalysisJob oluştur (file_type=json)
    4. Transactions'ları Redis'e kaydet
    5. CFO pipeline'ı tetikle (analyze=true ise)

    Returns: job_id + fatura sayısı + dönem özeti
    """
    from app.services.gib_efatura import get_efatura_client, GIBError

    client = get_efatura_client()
    if not client:
        raise HTTPException(
            status_code=503,
            detail=(
                "GİB e-Fatura yapılandırılmamış. "
                "GIB_VKN, GIB_USERNAME, GIB_PASSWORD değerlerini .env'e ekleyin."
            ),
        )

    try:
        await client.authenticate()
        invoices = await client.get_all_transactions(body.start_date, body.end_date)
    except GIBError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    finally:
        await client.close()

    if not invoices:
        return {
            "data": {
                "job_id":        None,
                "invoice_count": 0,
                "message":       "Bu dönemde e-Fatura verisi bulunamadı.",
            },
            "error": None,
        }

    # Create analysis job
    from app.models.analysis_job import AnalysisJob, JobStatus
    job = AnalysisJob(
        id=str(uuid.uuid4()),
        status=JobStatus.PENDING,
        filename=f"efatura_{body.start_date}_{body.end_date}.json",
        file_path="",
        file_type="json",
    )
    db.add(job)
    await db.commit()

    queued = False
    if body.analyze:
        try:
            from app.worker import get_arq_pool, enqueue_analysis
            import json
            pool = await get_arq_pool()
            await pool.set(
                f"ob_transactions:{job.id}",
                json.dumps(invoices),
                ex=3600,
            )
            await enqueue_analysis(job.id)
            queued = True
        except Exception as exc:
            logger.warning("Could not enqueue e-Fatura analysis: %s", exc)

    inbound  = [inv for inv in invoices if inv.get("direction") == "inbound"]
    outbound = [inv for inv in invoices if inv.get("direction") == "outbound"]

    return {
        "data": {
            "job_id":        job.id,
            "invoice_count": len(invoices),
            "inbound_count": len(inbound),
            "outbound_count": len(outbound),
            "period":        f"{body.start_date} – {body.end_date}",
            "total_income":  sum(inv.get("gross_amount", 0) for inv in outbound),
            "total_expense": sum(inv.get("gross_amount", 0) for inv in inbound),
            "queued":        queued,
            "poll_url":      f"/api/v1/analysis/{job.id}" if queued else None,
        },
        "error": None,
    }
