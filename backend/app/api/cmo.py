"""
CMO API endpoints -- /api/v1/cmo/*

POST /cmo/analyze       -> run CMO pipeline synchronously
GET  /cmo/health-check  -> verify agents are importable
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter()


# -- Request schema -----------------------------------------------------------

class CMOAnalyzeRequest(BaseModel):
    """
    CMO analysis request -- provide at least one data source.
    All fields optional; agents gracefully skip missing inputs.
    """
    company_name: str | None = None
    period: str | None = None
    campaign_csv: str | None = None   # Google Ads / Meta Ads CSV
    funnel_csv: str | None = None     # HubSpot / Salesforce CSV
    cohort_csv: str | None = None     # Mixpanel / Amplitude CSV


# -- Endpoints ----------------------------------------------------------------

@router.post("/cmo/analyze")
async def run_cmo_analysis(body: CMOAnalyzeRequest) -> dict[str, Any]:
    """
    Run CMO analysis pipeline and return results synchronously.
    At least one of campaign_csv, funnel_csv, cohort_csv is required.
    """
    from app.agents.cmo.orchestrator import run_cmo_pipeline

    if not any([body.campaign_csv, body.funnel_csv, body.cohort_csv]):
        raise HTTPException(
            status_code=400,
            detail=(
                "At least one data source required: "
                "campaign_csv, funnel_csv, or cohort_csv."
            ),
        )

    job_id = str(uuid.uuid4())

    try:
        result = await run_cmo_pipeline(
            job_id=job_id,
            company_name=body.company_name,
            period=body.period,
            campaign_csv=body.campaign_csv,
            funnel_csv=body.funnel_csv,
            cohort_csv=body.cohort_csv,
        )

        logs_serializable = [
            {
                "step":       lg.step,
                "ok":         lg.ok,
                "detail":     lg.detail,
                "confidence": lg.confidence,
            }
            for lg in (result.get("logs") or [])
        ]

        return {
            "data": {
                "job_id":          job_id,
                "campaigns":       result.get("campaigns"),
                "funnel":          result.get("funnel"),
                "cohorts":         result.get("cohorts"),
                "cmo_summary":     result.get("cmo_summary"),
                "logs":            logs_serializable,
                "error":           result.get("error"),
            },
            "error": None,
        }

    except Exception as exc:
        logger.exception("CMO pipeline failed for job=%s", job_id)
        raise HTTPException(status_code=500, detail=f"CMO analysis failed: {exc}")


@router.get("/cmo/health-check")
async def cmo_health() -> dict[str, Any]:
    """Verify CMO pipeline agents are importable and graph compiles."""
    from app.agents.cmo.orchestrator import _cmo_graph
    return {
        "data": {
            "status":     "ok",
            "graph_nodes": list(_cmo_graph.nodes.keys())
                           if hasattr(_cmo_graph, "nodes") else [],
            "agents": ["campaigns", "funnel", "cohort", "cmo_summary"],
        },
        "error": None,
    }
