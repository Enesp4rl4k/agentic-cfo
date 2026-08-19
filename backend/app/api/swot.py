"""
SWOT Analysis API

POST /swot/analyze     -- Tum C-Suite verilerinden SWOT olustur
GET  /swot/{job_id}    -- Mevcut job'dan SWOT uret
POST /swot/from-org    -- CompanyContext'ten SWOT olustur

Her SWOT maddesi:
  - domain: hangi C-Suite alanından geldiği
  - priority: 1-10 öncelik skoru
  - evidence: kanıt zinciri
  - action: önerilen aksiyon
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from app.api.auth import get_current_user
from app.database import get_db
from app.models.user import User

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Request schemalar ─────────────────────────────────────────────────────────

class SWOTFromDataRequest(BaseModel):
    """Dogrudan veri ile SWOT olustur."""
    pnl:          dict[str, Any] | None = None
    cashflow:     dict[str, Any] | None = None
    forecast:     dict[str, Any] | None = None
    chro_data:    dict[str, Any] | None = None
    cto_data:     dict[str, Any] | None = None
    cmo_data:     dict[str, Any] | None = None
    coo_data:     dict[str, Any] | None = None
    company_name: str | None = None
    use_llm:      bool = Field(True, description="LLM ile ozet zenginlestir")


class SWOTFromJobRequest(BaseModel):
    """Job ID'den SWOT olustur."""
    job_id:       str
    use_llm:      bool = True
    company_name: str | None = None


class SWOTFromOrgRequest(BaseModel):
    """CompanyContext'ten SWOT olustur."""
    org_id:       str
    use_llm:      bool = True


# ── Context loaders ───────────────────────────────────────────────────────────

async def _load_from_job(job_id: str, db: AsyncSession) -> dict[str, Any]:
    """Job'a ait son JSON raporu yukle."""
    try:
        from app.models.report import Report, ReportFormat  # type: ignore[attr-defined]
        stmt = (
            select(Report)
            .where(Report.job_id == job_id, Report.format == ReportFormat.JSON)
            .order_by(desc(Report.created_at))
            .limit(1)
        )
        row = (await db.execute(stmt)).scalar_one_or_none()
        if not row or not row.content:
            return {}
        import json
        data = json.loads(row.content) if isinstance(row.content, str) else row.content
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.debug("Job verisi yuklenemedi: %s", exc)
        return {}


async def _load_from_org(org_id: str) -> dict[str, Any]:
    """CompanyContext'ten tum agent sonuclarini yukle."""
    try:
        from app.services.company_context import get_company_context
        ctx = await get_company_context(org_id)
        if not ctx:
            return {}
        results = ctx.get("agent_results") or {}
        cfo_r = results.get("cfo") or {}
        return {
            "pnl":      cfo_r.get("pnl") or {},
            "cashflow": cfo_r.get("cashflow") or {},
            "forecast": cfo_r.get("forecast") or {},
            "chro_data": results.get("chro") or {},
            "cto_data":  results.get("cto") or {},
            "cmo_data":  results.get("cmo") or {},
            "coo_data":  results.get("coo") or {},
        }
    except Exception as exc:
        logger.debug("Org context yuklenemedi: %s", exc)
        return {}


# ── Endpoint'ler ───────────────────────────────────────────────────────────────

@router.post("/swot/analyze")
async def swot_from_data(
    req: SWOTFromDataRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Dogrudan C-Suite verileri ile SWOT matrisi olustur.

    Her kategori (S/W/O/T) maddeler listesi doner:
      - text: kisa aciklama
      - domain: hangi C-Suite alani
      - priority: 1-10 onem skoru
      - evidence: veri kaniti
      - action: onerilen aksiyon

    LLM aktifse Turkce yonetici ozeti de eklenir.
    """
    from app.agents.ceo.swot_agent import run_swot_from_context

    try:
        result = await run_swot_from_context(
            pnl=req.pnl,
            cashflow=req.cashflow,
            forecast=req.forecast,
            chro_data=req.chro_data,
            cto_data=req.cto_data,
            cmo_data=req.cmo_data,
            coo_data=req.coo_data,
            company_name=req.company_name,
            use_llm=req.use_llm,
        )
    except Exception as exc:
        logger.exception("SWOT analiz hatasi: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    return _format_response(result)


@router.post("/swot/from-job")
async def swot_from_job(
    req: SWOTFromJobRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Mevcut bir CFO analiz job'undan SWOT uret.
    job_id: onceden calistirilmis analiz job'u
    """
    from app.agents.ceo.swot_agent import run_swot_from_context

    data = await _load_from_job(req.job_id, db)
    if not data:
        raise HTTPException(
            status_code=404,
            detail=f"Job {req.job_id} icin rapor bulunamadi"
        )

    try:
        result = await run_swot_from_context(
            pnl=data.get("pnl"),
            cashflow=data.get("cashflow"),
            forecast=data.get("forecast"),
            company_name=req.company_name,
            use_llm=req.use_llm,
        )
    except Exception as exc:
        logger.exception("SWOT job analiz hatasi: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    return _format_response(result, job_id=req.job_id)


@router.post("/swot/from-org")
async def swot_from_org(
    req: SWOTFromOrgRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    CompanyContext'teki tum agent sonuclarindan SWOT uret.
    Tum C-Suite verilerini (CFO+CHRO+CTO+CMO+COO) kullanir.
    """
    from app.agents.ceo.swot_agent import run_swot_from_context

    ctx = await _load_from_org(req.org_id)
    if not ctx:
        raise HTTPException(
            status_code=404,
            detail=f"Org {req.org_id} icin veri bulunamadi"
        )

    try:
        result = await run_swot_from_context(
            pnl=ctx.get("pnl"),
            cashflow=ctx.get("cashflow"),
            forecast=ctx.get("forecast"),
            chro_data=ctx.get("chro_data"),
            cto_data=ctx.get("cto_data"),
            cmo_data=ctx.get("cmo_data"),
            coo_data=ctx.get("coo_data"),
            use_llm=req.use_llm,
        )
    except Exception as exc:
        logger.exception("SWOT org analiz hatasi: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    return _format_response(result, org_id=req.org_id)


# ── Response formatter ────────────────────────────────────────────────────────

def _format_response(
    result: dict[str, Any],
    job_id: str | None = None,
    org_id: str | None = None,
) -> dict[str, Any]:
    """
    SWOT sonucunu standart API response formatina donustur.

    Ozet istatistikler ve matris birlikte doner.
    """
    matrix = result.get("swot_matrix") or {}
    strengths     = matrix.get("strengths", [])
    weaknesses    = matrix.get("weaknesses", [])
    opportunities = matrix.get("opportunities", [])
    threats       = matrix.get("threats", [])

    # Domain dagılımı
    domains_involved: set[str] = set()
    for lst in [strengths, weaknesses, opportunities, threats]:
        for item in lst:
            domains_involved.update(item.get("domain", "").split("+"))

    # Ortalama oncelik skoru
    all_items = strengths + weaknesses + opportunities + threats
    avg_priority = (
        sum(i.get("priority", 5) for i in all_items) / len(all_items)
        if all_items else 0
    )

    # En kritik maddeler (oncelik >= 8)
    critical_items = [i for i in all_items if i.get("priority", 0) >= 8]

    return {
        "ok":          result.get("ok", True),
        "confidence":  result.get("confidence", 0.7),
        "detail":      result.get("detail", ""),
        "job_id":      job_id,
        "org_id":      org_id,

        # Ozet istatistikler
        "summary": {
            "total_items":       len(all_items),
            "strengths_count":   len(strengths),
            "weaknesses_count":  len(weaknesses),
            "opportunities_count": len(opportunities),
            "threats_count":     len(threats),
            "critical_items":    len(critical_items),
            "avg_priority":      round(avg_priority, 1),
            "domains_involved":  sorted(domains_involved - {""}),
            "balance_score": round(
                (len(strengths) + len(opportunities) - len(weaknesses) - len(threats))
                / max(1, len(all_items)) * 10, 1
            ),
        },

        # SWOT matrisi
        "matrix": {
            "strengths":     strengths,
            "weaknesses":    weaknesses,
            "opportunities": opportunities,
            "threats":       threats,
        },

        # En kritik maddeler (quick actions)
        "critical_items":   critical_items,

        # LLM ozet
        "executive_summary": result.get("swot_summary", ""),
    }
