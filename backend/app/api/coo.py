"""
COO API endpoints -- /api/v1/coo/*

POST /coo/analyze       -> run COO pipeline synchronously
GET  /coo/health-check  -> verify agents are importable
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

class COOAnalyzeRequest(BaseModel):
    """
    COO analysis request -- provide at least one data source.
    All fields optional; agents gracefully skip missing inputs.
    """
    company_name: str | None = None
    period: str | None = None
    process_csv: str | None = None    # Process/workflow metrics CSV
    resource_csv: str | None = None   # Team headcount & utilization CSV
    sla_csv: str | None = None        # SLA / ticket data CSV


# -- Endpoints ----------------------------------------------------------------

@router.post("/coo/analyze")
async def run_coo_analysis(body: COOAnalyzeRequest) -> dict[str, Any]:
    """
    Run COO analysis pipeline and return results synchronously.
    At least one of process_csv, resource_csv, sla_csv is required.
    """
    from app.agents.coo.orchestrator import run_coo_pipeline

    if not any([body.process_csv, body.resource_csv, body.sla_csv]):
        raise HTTPException(
            status_code=400,
            detail=(
                "At least one data source required: "
                "process_csv, resource_csv, or sla_csv."
            ),
        )

    job_id = str(uuid.uuid4())

    try:
        result = await run_coo_pipeline(
            job_id=job_id,
            company_name=body.company_name,
            period=body.period,
            process_csv=body.process_csv,
            resource_csv=body.resource_csv,
            sla_csv=body.sla_csv,
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
                "job_id":       job_id,
                "processes":    result.get("processes"),
                "resources":    result.get("resources"),
                "sla":          result.get("sla"),
                "coo_summary":  result.get("coo_summary"),
                "logs":         logs_serializable,
                "error":        result.get("error"),
            },
            "error": None,
        }

    except Exception as exc:
        logger.exception("COO pipeline failed for job=%s", job_id)
        raise HTTPException(status_code=500, detail=f"COO analysis failed: {exc}")


@router.get("/coo/health-check")
async def coo_health() -> dict[str, Any]:
    """Verify COO pipeline agents are importable and graph compiles."""
    from app.agents.coo.orchestrator import _coo_graph
    return {
        "data": {
            "status":      "ok",
            "graph_nodes": list(_coo_graph.nodes.keys())
                           if hasattr(_coo_graph, "nodes") else [],
            "agents": ["process", "resource", "sla", "coo_summary"],
        },
        "error": None,
    }
