"""
Internal Audit API Endpoints

POST /audit/analyze  — Run Internal Audit pipeline
GET  /audit/health-check
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.agents.audit.orchestrator import run_audit_pipeline

router = APIRouter()


class AuditAnalyzeRequest(BaseModel):
    findings_csv: str = ""
    controls_csv: str = ""
    coverage_csv: str = ""
    company_name: str | None = None
    audit_period: str | None = None


@router.post("/audit/analyze")
async def run_audit_analysis(body: AuditAnalyzeRequest) -> dict[str, Any]:
    """Run Internal Audit pipeline — findings, controls, coverage."""
    try:
        job_id = str(uuid.uuid4())
        result = await run_audit_pipeline(
            findings_csv=body.findings_csv,
            controls_csv=body.controls_csv,
            coverage_csv=body.coverage_csv,
            company_name=body.company_name,
            audit_period=body.audit_period,
        )
        logs_serializable = [
            {"node": l.node, "status": l.status,
             "message": l.message, "metrics": l.metrics}
            for l in (result.get("logs") or [])
        ]
        return {
            "job_id":        job_id,
            "findings":      result.get("findings"),
            "controls":      result.get("controls"),
            "coverage":      result.get("coverage"),
            "audit_summary": result.get("audit_summary"),
            "logs":          logs_serializable,
            "error":         result.get("error"),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Audit analysis failed: {exc}")


@router.get("/audit/health-check")
async def audit_health() -> dict[str, Any]:
    return {
        "status": "healthy",
        "service": "internal_audit",
        "capabilities": [
            "findings_tracking", "control_effectiveness",
            "audit_universe_coverage", "maturity_assessment",
        ],
    }
