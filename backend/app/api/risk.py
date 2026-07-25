"""
Risk Agent API Endpoints

POST /risk/analyze  — Run full Risk pipeline (register, losses, KRIs)
GET  /risk/health-check — Service health
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.agents.risk.orchestrator import run_risk_pipeline

router = APIRouter()


class RiskAnalyzeRequest(BaseModel):
    register_csv: str = ""
    loss_csv: str = ""
    kri_csv: str = ""
    company_name: str | None = None
    reporting_period: str | None = None


@router.post("/risk/analyze")
async def run_risk_analysis(body: RiskAnalyzeRequest) -> dict[str, Any]:
    """
    Run full Risk pipeline synchronously.
    Returns: { job_id, register, losses, kris, risk_summary, logs, error }
    """
    try:
        job_id = str(uuid.uuid4())
        result = await run_risk_pipeline(
            register_csv=body.register_csv,
            loss_csv=body.loss_csv,
            kri_csv=body.kri_csv,
            company_name=body.company_name,
            reporting_period=body.reporting_period,
        )

        logs_serializable = [
            {
                "node":    log.node,
                "status":  log.status,
                "message": log.message,
                "metrics": log.metrics,
            }
            for log in (result.get("logs") or [])
        ]

        return {
            "job_id":       job_id,
            "register":     result.get("register"),
            "losses":       result.get("losses"),
            "kris":         result.get("kris"),
            "risk_summary": result.get("risk_summary"),
            "logs":         logs_serializable,
            "error":        result.get("error"),
        }

    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Risk analysis failed: {exc}")


@router.get("/risk/health-check")
async def risk_health() -> dict[str, Any]:
    return {
        "status": "healthy",
        "service": "risk",
        "capabilities": [
            "risk_register_scoring",
            "loss_event_tracking",
            "kri_threshold_monitoring",
            "enterprise_risk_posture",
        ],
    }
