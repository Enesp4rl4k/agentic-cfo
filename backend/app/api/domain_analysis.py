"""Alan analizi rotaları — her alan için tek giriş noktası.

GET  /analysis/{job_id}/domains            — yedi alanın her biri: ne var, ne eksik
GET  /analysis/{job_id}/domains/{domain}   — tek alanın durumu (çalıştırmadan)
POST /analysis/{job_id}/domains/{domain}   — gerçek veriyle analiz; yoksa neden

Replaces the /cto-kernel, /cmo-kernel, /chro-kernel, /coo-kernel,
/risk-kernel, /audit-kernel and /compliance-kernel estimates. See
app/agents/orchestration/domain_analysis.py.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.orchestration import domain_analysis as da
from app.api.access import owned_job
from app.database import get_db
from app.models.analysis_job import AnalysisJob

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/analysis/{job_id}/domains")
async def list_domains(
    job_id: str,
    job: AnalysisJob = Depends(owned_job),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return {"data": [await da.durum(db, job, kod) for kod in da.ALANLAR], "error": None}


@router.get("/analysis/{job_id}/domains/{domain}")
async def domain_status(
    job_id: str,
    domain: str,
    job: AnalysisJob = Depends(owned_job),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        return {"data": await da.durum(db, job, domain), "error": None}
    except da.AlanBilinmiyor as exc:
        raise HTTPException(status_code=404, detail=f"Bilinmeyen alan: {domain}") from exc


@router.post("/analysis/{job_id}/domains/{domain}")
async def run_domain(
    job_id: str,
    domain: str,
    job: AnalysisJob = Depends(owned_job),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        out = await da.analiz_et(db, job, domain)
    except da.AlanBilinmiyor as exc:
        raise HTTPException(status_code=404, detail=f"Bilinmeyen alan: {domain}") from exc
    except ValueError as exc:
        # An orchestrator refusing the file's shape is the user's file, not a server fault.
        raise HTTPException(status_code=422, detail=f"Dosya bu alan için okunamadı: {exc}") from exc

    # A real result becomes the organisation's latest for the domain, so the
    # cross-domain report and the CEO view read it. Estimates are never stored:
    # there are none to store.
    if out["durum"] == da.ANALIZ_EDILDI and job.org_id:
        try:
            from app.agents.orchestration.auto_chain import on_agent_complete
            from app.services.context_persist import persist_agent_completion

            await persist_agent_completion(
                str(job.org_id), domain, out["sonuc"], db,
                job_id=job.id, auto_chain_hook=on_agent_complete,
            )
        except Exception as exc:
            logger.warning("Alan sonucu bağlama yazılamadı (%s): %s", domain, exc)
    return {"data": out, "error": None}
