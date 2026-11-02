"""
Internal Audit API Endpoints

POST /audit/analyze  — Run Internal Audit pipeline
GET  /audit/health-check
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.audit.orchestrator import run_audit_pipeline
from app.agents.run_ledger import recorded_run
from app.api.auth import get_current_user
from app.database import get_db
from app.models.user import User

router = APIRouter()


class AuditAnalyzeRequest(BaseModel):
    findings_csv: str = ""
    controls_csv: str = ""
    coverage_csv: str = ""
    company_name: str | None = None
    audit_period: str | None = None


@router.post("/audit/analyze")
async def run_audit_analysis(
    body: AuditAnalyzeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Run Internal Audit pipeline — findings, controls, coverage."""
    try:
        job_id = str(uuid.uuid4())
        result = await recorded_run(db, "audit", current_user.org_id, job_id, run_audit_pipeline(
            findings_csv=body.findings_csv,
            controls_csv=body.controls_csv,
            coverage_csv=body.coverage_csv,
            company_name=body.company_name,
            audit_period=body.audit_period,
        ))
        inceleme = None
        if current_user.org_id and not result.get("error"):
            from app.agents.orchestration.auto_chain import on_agent_complete
            from app.services.context_persist import persist_agent_completion

            # Below the gate this waits in the owner's queue.
            inceleme = await persist_agent_completion(
                str(current_user.org_id), "audit", dict(result), db,
                job_id=job_id, company_name=body.company_name,
                reporting_period=body.audit_period, auto_chain_hook=on_agent_complete,
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
            "inceleme":      inceleme,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Audit analysis failed: {exc}")


@router.get("/audit/health-check")
async def audit_health(current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    return {
        "status": "healthy",
        "service": "internal_audit",
        "capabilities": [
            "findings_tracking", "control_effectiveness",
            "audit_universe_coverage", "maturity_assessment",
        ],
    }
