"""
CHRO API Endpoints

POST /chro/analyze - Run CHRO pipeline (headcount, attrition, compensation analysis)
GET /chro/health-check - Service health check
"""

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.chro.orchestrator import run_chro_pipeline
from app.api.auth import get_current_user
from app.database import get_db
from app.models.user import User

router = APIRouter()
logger = logging.getLogger(__name__)


class CHROAnalyzeRequest(BaseModel):
    """Request for CHRO analysis."""
    headcount_csv: str
    attrition_csv: str
    compensation_csv: str
    company_name: str | None = None
    analysis_period: str | None = None


@router.post("/chro/analyze")
async def run_chro_analysis(
    body: CHROAnalyzeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Run CHRO pipeline synchronously.
    Analyzes headcount, attrition, and compensation data.
    Returns: { job_id, headcount, attrition, compensation, chro_summary, logs, error }
    """

    try:
        job_id = str(uuid.uuid4())

        result = await run_chro_pipeline(
            headcount_csv=body.headcount_csv,
            attrition_csv=body.attrition_csv,
            compensation_csv=body.compensation_csv,
            company_name=body.company_name,
            analysis_period=body.analysis_period,
        )

        if current_user.org_id and not result.get("error"):
            try:
                from app.agents.orchestration.auto_chain import on_agent_complete
                from app.services.context_persist import persist_agent_completion

                await persist_agent_completion(
                    str(current_user.org_id),
                    "chro",
                    dict(result),
                    db,
                    job_id=job_id,
                    company_name=body.company_name,
                    reporting_period=body.analysis_period,
                    auto_chain_hook=on_agent_complete,
                )
            except Exception as exc:
                logger.warning("CHRO context persist failed: %s", exc)

        # Serialize logs
        logs_serializable = [
            {
                "node": log.node,
                "status": log.status,
                "message": log.message,
                "metrics": log.metrics,
            }
            for log in (result.get("logs") or [])
        ]

        return {
            "job_id": job_id,
            "headcount": result.get("headcount"),
            "attrition": result.get("attrition"),
            "compensation": result.get("compensation"),
            "chro_summary": result.get("chro_summary"),
            "logs": logs_serializable,
            "error": result.get("error"),
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"CHRO analysis failed: {e!s}")


@router.get("/chro/health-check")
async def chro_health(current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    """Health check for CHRO service."""
    return {
        "status": "healthy",
        "service": "chro",
        "capabilities": ["headcount_analysis", "attrition_analysis", "compensation_analysis"],
    }
