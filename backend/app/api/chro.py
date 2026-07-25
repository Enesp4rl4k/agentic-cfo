"""
CHRO API Endpoints

POST /chro/analyze - Run CHRO pipeline (headcount, attrition, compensation analysis)
GET /chro/health-check - Service health check
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Any
import uuid

from app.agents.chro.orchestrator import run_chro_pipeline

router = APIRouter()


class CHROAnalyzeRequest(BaseModel):
    """Request for CHRO analysis."""
    headcount_csv: str
    attrition_csv: str
    compensation_csv: str
    company_name: str | None = None
    analysis_period: str | None = None


@router.post("/chro/analyze")
async def run_chro_analysis(body: CHROAnalyzeRequest) -> dict[str, Any]:
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
        raise HTTPException(status_code=500, detail=f"CHRO analysis failed: {str(e)}")


@router.get("/chro/health-check")
async def chro_health() -> dict[str, Any]:
    """Health check for CHRO service."""
    return {
        "status": "healthy",
        "service": "chro",
        "capabilities": ["headcount_analysis", "attrition_analysis", "compensation_analysis"],
    }
