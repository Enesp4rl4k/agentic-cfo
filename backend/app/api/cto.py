"""
CTO API endpoints — /api/v1/cto/*

POST /cto/analyze     → run CTO pipeline (async via ARQ)
GET  /cto/{job_id}    → get CTO analysis result
POST /cto/analyze/sync → run CTO pipeline synchronously (dev/test only)
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Request/Response schemas ───────────────────────────────────────────────────

class CTOAnalyzeRequest(BaseModel):
    """
    CTO analysis request — provide at least one data source.

    All fields are optional; agents gracefully skip missing inputs.
    """
    company_name: str | None = None
    cloud_billing_csv: str | None = None   # raw CSV text
    git_log_text: str | None = None        # git log --stat output
    incident_csv: str | None = None        # PagerDuty / OpsGenie CSV
    sprint_csv: str | None = None          # Jira / Linear sprint CSV


# ── Sync endpoint (dev / small payloads) ──────────────────────────────────────

@router.post("/cto/analyze")
async def run_cto_analysis(
    body: CTOAnalyzeRequest,
) -> dict[str, Any]:
    """
    Run CTO analysis pipeline and return results synchronously.

    For production use with large datasets, use /cto/analyze/async to
    offload to the ARQ worker queue.
    """
    from app.agents.cto.orchestrator import run_cto_pipeline

    if not any([
        body.cloud_billing_csv,
        body.git_log_text,
        body.incident_csv,
        body.sprint_csv,
    ]):
        raise HTTPException(
            status_code=400,
            detail="At least one data source required: cloud_billing_csv, git_log_text, incident_csv, or sprint_csv.",
        )

    job_id = str(uuid.uuid4())

    try:
        result = await run_cto_pipeline(
            job_id=job_id,
            cloud_billing_csv=body.cloud_billing_csv,
            git_log_text=body.git_log_text,
            incident_csv=body.incident_csv,
            sprint_csv=body.sprint_csv,
            company_name=body.company_name,
        )

        # Serialize logs (dataclass → dict)
        logs_serializable = [
            {
                "step": lg.step,
                "ok": lg.ok,
                "detail": lg.detail,
                "confidence": lg.confidence,
            }
            for lg in (result.get("logs") or [])
        ]

        return {
            "data": {
                "job_id": job_id,
                "awaiting_review": result.get("awaiting_review", False),
                "min_confidence": result.get("min_confidence"),
                "infra": result.get("infra"),
                "tech_debt": result.get("tech_debt"),
                "incidents": result.get("incidents"),
                "velocity": result.get("velocity"),
                "cto_summary": result.get("cto_summary"),
                "logs": logs_serializable,
                "error": result.get("error"),
            },
            "error": None,
        }

    except Exception as exc:
        logger.exception("CTO pipeline failed for job=%s", job_id)
        raise HTTPException(status_code=500, detail=f"CTO analysis failed: {exc}")


@router.get("/cto/summary/{job_id}")
async def get_cto_summary(job_id: str) -> dict[str, Any]:
    """
    Get stored CTO summary for a given job_id.
    Returns 404 if not found — use /cto/analyze to generate first.
    """
    # In a full implementation this would query a CTOJob DB table.
    # For now we return a 404 — callers should use the sync endpoint or
    # store results client-side.
    raise HTTPException(
        status_code=404,
        detail=(
            "CTO job results are not persisted yet. "
            "Use POST /api/v1/cto/analyze to get results synchronously."
        ),
    )


@router.get("/cto/health-check")
async def cto_health() -> dict[str, Any]:
    """Verify CTO pipeline agents are importable and graph compiles."""
    from app.agents.cto.orchestrator import cto_graph
    return {
        "data": {
            "status": "ok",
            "graph_nodes": list(cto_graph.nodes.keys()) if hasattr(cto_graph, "nodes") else [],
            "agents": ["infra", "tech_debt", "incidents", "velocity", "cto_summary"],
        },
        "error": None,
    }
