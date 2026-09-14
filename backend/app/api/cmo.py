"""
CMO API endpoints -- /api/v1/cmo/*

POST /cmo/analyze       -> run CMO pipeline synchronously
GET  /cmo/health-check  -> verify agents are importable
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.models.user import User

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
async def run_cmo_analysis(
    body: CMOAnalyzeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
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

        if current_user.org_id and not result.get("error"):
            try:
                from app.agents.orchestration.auto_chain import on_agent_complete
                from app.services.context_persist import persist_agent_completion

                await persist_agent_completion(
                    str(current_user.org_id),
                    "cmo",
                    dict(result),
                    db,
                    job_id=job_id,
                    company_name=body.company_name,
                    reporting_period=body.period,
                    auto_chain_hook=on_agent_complete,
                )
            except Exception as exc:
                logger.warning("CMO context persist failed: %s", exc)

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
async def cmo_health(current_user: User = Depends(get_current_user)) -> dict[str, Any]:
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
