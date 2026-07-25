"""
Benchmark API — sector comparison endpoints.

GET  /api/v1/benchmark/{job_id}
     Full benchmark comparison for a job's P&L data against sector medians.

GET  /api/v1/benchmark/{job_id}/metric/{metric}
     Single metric comparison with interpretation.

GET  /api/v1/benchmark/sectors
     List available sectors and metrics.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.report import Report, ReportFormat

router = APIRouter()
logger = logging.getLogger(__name__)

_VALID_METRICS = [
    "gross_margin", "net_margin", "ebitda_margin",
    "opex_to_revenue", "revenue_growth_yoy",
]

_VALID_SECTORS = [
    "retail", "manufacturing", "technology", "construction",
    "services", "food_beverage", "logistics", "default",
]


async def _get_pnl(job_id: str, db: AsyncSession) -> dict[str, Any]:
    result = await db.execute(
        select(Report)
        .where(Report.job_id == job_id, Report.report_format == ReportFormat.JSON)
        .order_by(desc(Report.created_at))
        .limit(1)
    )
    rep = result.scalar_one_or_none()
    if not rep or not rep.data:
        raise HTTPException(
            status_code=404,
            detail=f"Job '{job_id}' için analiz verisi bulunamadı.",
        )
    pnl = rep.data.get("pnl")
    if not pnl:
        raise HTTPException(status_code=422, detail="P&L verisi eksik.")
    return pnl


@router.get("/benchmark/sectors")
async def list_sectors() -> dict[str, Any]:
    """List available sectors and metrics for benchmarking."""
    return {
        "data": {
            "sectors": [
                {"key": "retail",        "label": "Perakende"},
                {"key": "manufacturing", "label": "Üretim / İmalat"},
                {"key": "technology",    "label": "Teknoloji / Yazılım"},
                {"key": "construction",  "label": "İnşaat / Gayrimenkul"},
                {"key": "services",      "label": "Hizmet"},
                {"key": "food_beverage", "label": "Yiyecek-İçecek"},
                {"key": "logistics",     "label": "Lojistik / Nakliye"},
                {"key": "default",       "label": "Genel Ortalama"},
            ],
            "metrics": [
                {"key": "gross_margin",      "label": "Brüt Kâr Marjı", "unit": "%"},
                {"key": "net_margin",        "label": "Net Kâr Marjı", "unit": "%"},
                {"key": "ebitda_margin",     "label": "FAVÖK Marjı", "unit": "%"},
                {"key": "opex_to_revenue",   "label": "Gider/Ciro Oranı", "unit": "%"},
                {"key": "revenue_growth_yoy", "label": "Yıllık Büyüme", "unit": "%"},
            ],
            "source": "TCMB/BDDK Sektör İstatistikleri 2023-2024",
        },
        "error": None,
    }


@router.get("/benchmark/{job_id}")
async def get_full_benchmark(
    job_id: str,
    sector: str = Query(default="default", description="Sektör kodu"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Full benchmark report comparing all P&L metrics against sector medians.

    Returns per-metric comparison with:
    - Company value vs sector p25/p50/p75
    - Percentile position (bottom_25 / p25_p50 / p50_p75 / top_25)
    - Turkish interpretation and recommendation
    - Overall sector score
    """
    if sector not in _VALID_SECTORS:
        raise HTTPException(
            status_code=400,
            detail=f"Geçersiz sektör: '{sector}'. Geçerli: {_VALID_SECTORS}",
        )

    pnl = await _get_pnl(job_id, db)

    from app.services.benchmark import get_benchmark_engine
    engine = get_benchmark_engine()
    comparison = engine.build_full_comparison(pnl, sector=sector)

    return {"data": comparison, "error": None}


@router.get("/benchmark/{job_id}/metric/{metric}")
async def get_metric_benchmark(
    job_id: str,
    metric: str = Path(..., description="Metrik kodu"),
    sector: str = Query(default="default", description="Sektör kodu"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Single metric benchmark comparison.

    Example:
      GET /benchmark/{job_id}/metric/gross_margin?sector=technology
    """
    if metric not in _VALID_METRICS:
        raise HTTPException(
            status_code=400,
            detail=f"Geçersiz metrik: '{metric}'. Geçerli: {_VALID_METRICS}",
        )
    if sector not in _VALID_SECTORS:
        raise HTTPException(
            status_code=400,
            detail=f"Geçersiz sektör: '{sector}'.",
        )

    pnl = await _get_pnl(job_id, db)

    # Get metric value from P&L
    metric_value_map = {
        "gross_margin":      pnl.get("gross_margin", 0),
        "net_margin":        pnl.get("net_margin", 0),
        "ebitda_margin":     pnl.get("ebitda_margin", 0),
        "opex_to_revenue":   (pnl.get("total_opex", 0) / pnl["revenue"]) if pnl.get("revenue", 0) > 0 else 0,
        "revenue_growth_yoy": 0,  # Requires multi-period data
    }
    company_value = metric_value_map.get(metric, 0)

    from app.services.benchmark import get_benchmark_engine
    engine = get_benchmark_engine()
    result = engine.compare_to_benchmark(metric, company_value, sector)

    return {"data": result, "error": None}
