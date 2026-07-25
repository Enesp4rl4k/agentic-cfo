"""
Causal Analysis API — nedensellik analizi endpoints.

POST /api/v1/analysis/{job_id}/causal
     Granger causality + lagged correlation + feature importance analizi.
     "Pazarlama harcaması geliri etkiliyor mu, kaç ay gecikmeyle?"

GET  /api/v1/analysis/{job_id}/causal/feature-importance
     Hangi gider kalemi net kâra en çok etki yapıyor?
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.report import Report, ReportFormat

router = APIRouter()
logger = logging.getLogger(__name__)

_VALID_METRICS = ["in", "out", "net", "revenue", "expenses"]


class CausalAnalysisRequest(BaseModel):
    metric_x: str = "in"       # Cause metric (gelir/income)
    metric_y: str = "out"      # Effect metric (gider/expense)
    max_lag:  int = 3          # Maximum months of lag to test (1-6)


async def _get_dashboard(job_id: str, db: AsyncSession) -> dict[str, Any]:
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
    return rep.data


@router.post("/analysis/{job_id}/causal")
async def run_causal_analysis(
    job_id: str,
    body: CausalAnalysisRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Nedensellik analizi: Granger causality + lagged correlation + feature importance.

    Örnek sorular:
    - "Pazarlama harcaması (out) geliri (in) Granger-cause yapıyor mu?"
    - "Net nakit akışı (net) ne zaman değişime uğruyor?"

    metric_x ve metric_y değerleri:
      "in"       → Nakit girişi (gelir)
      "out"      → Nakit çıkışı (gider)
      "net"      → Net nakit akışı
      "revenue"  → "in" ile aynı
      "expenses" → "out" ile aynı

    Gereksinim:
      - Granger testi için minimum 12 aylık veri
      - Korelasyon analizi için minimum 6 aylık veri
    """
    if body.metric_x not in _VALID_METRICS:
        raise HTTPException(
            status_code=400,
            detail=f"Geçersiz metric_x: '{body.metric_x}'. Geçerli: {_VALID_METRICS}",
        )
    if body.metric_y not in _VALID_METRICS:
        raise HTTPException(
            status_code=400,
            detail=f"Geçersiz metric_y: '{body.metric_y}'. Geçerli: {_VALID_METRICS}",
        )
    if body.metric_x == body.metric_y:
        raise HTTPException(
            status_code=400,
            detail="metric_x ve metric_y farklı olmalı.",
        )
    if not 1 <= body.max_lag <= 6:
        raise HTTPException(
            status_code=400,
            detail="max_lag 1 ile 6 arasında olmalı.",
        )

    dashboard = await _get_dashboard(job_id, db)
    monthly_series = (dashboard.get("cashflow") or {}).get("monthly_series") or []
    pnl = dashboard.get("pnl") or {}

    if not monthly_series:
        raise HTTPException(
            status_code=422,
            detail="Aylık nakit akış verisi bulunamadı. CFO analizini önce çalıştırın.",
        )

    from app.agents.causal_agent import run_causal_analysis
    result = run_causal_analysis(
        monthly_series=monthly_series,
        pnl=pnl,
        metric_x=body.metric_x,
        metric_y=body.metric_y,
        max_lag=body.max_lag,
    )

    return {"data": result, "error": None}


@router.get("/analysis/{job_id}/causal/feature-importance")
async def get_feature_importance(
    job_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Hangi gider kalemi net kâra en yüksek etkiyi yapıyor?

    Her gider kalemi için:
    - Gelire oranı (% cinsinden)
    - %10 azaltılırsa net kâra etkisi (sensitivity)
    - Sıralama

    Bu analiz "nereye odaklanayım?" sorusuna veri odaklı yanıt verir.
    """
    dashboard = await _get_dashboard(job_id, db)
    pnl = dashboard.get("pnl") or {}

    if not pnl:
        raise HTTPException(
            status_code=422,
            detail="P&L verisi bulunamadı.",
        )

    from app.agents.causal_agent import feature_importance_analysis
    result = feature_importance_analysis(pnl)

    return {"data": result, "error": None}
