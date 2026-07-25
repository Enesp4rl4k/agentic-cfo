"""
Compliance API endpoints — /api/v1/compliance/*

POST /compliance/analyze        → run compliance pipeline synchronously
GET  /compliance/health-check   → verify graph compiles
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Request / Response schemas ─────────────────────────────────────────────────

class ComplianceAnalyzeRequest(BaseModel):
    """
    Compliance analysis request — provide at least one CSV data source.

    All fields are optional; agents gracefully skip missing inputs.

    policy_csv columns:
        policy, severity, status, last_review, owner, category

    violations_csv columns:
        violation, policy_id, severity, date_found, due_date,
        remediation_status, responsible_party, framework

    regulations_csv columns:
        regulation, requirement, compliance_status, last_audit,
        next_audit, control_owner, evidence_status, risk_level
    """
    company_name:    str | None = None
    audit_period:    str | None = None   # e.g. "2024-Q2", "2024-06"
    policy_csv:      str | None = None
    violations_csv:  str | None = None
    regulations_csv: str | None = None


# ── Sync endpoint ──────────────────────────────────────────────────────────────

@router.post("/compliance/analyze")
async def run_compliance_analysis(
    body: ComplianceAnalyzeRequest,
) -> dict[str, Any]:
    """
    Run Compliance analysis pipeline and return results synchronously.

    Returns a unified compliance health score (0–100), component breakdowns
    (policies, violations, regulations), alerts, and actionable recommendations.
    """
    from app.agents.compliance.orchestrator import run_compliance_pipeline

    if not any([body.policy_csv, body.violations_csv, body.regulations_csv]):
        raise HTTPException(
            status_code=400,
            detail=(
                "At least one data source required: "
                "policy_csv, violations_csv, or regulations_csv."
            ),
        )

    job_id = str(uuid.uuid4())

    try:
        result = await run_compliance_pipeline(
            job_id=job_id,
            policy_csv=body.policy_csv,
            violations_csv=body.violations_csv,
            regulations_csv=body.regulations_csv,
            company_name=body.company_name,
            audit_period=body.audit_period,
        )

        # Serialize logs (dataclass → dict)
        logs_serializable = [
            {
                "node":    lg.node,
                "status":  lg.status,
                "message": lg.message,
                "metrics": lg.metrics,
            }
            for lg in (result.get("logs") or [])
        ]

        return {
            "data": {
                "job_id":             job_id,
                "company_name":       body.company_name,
                "audit_period":       body.audit_period,
                "policies":           result.get("policies"),
                "violations":         result.get("violations"),
                "regulations":        result.get("regulations"),
                "compliance_summary": result.get("compliance_summary"),
                "logs":               logs_serializable,
                "error":              result.get("error"),
            },
            "error": None,
        }

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Compliance pipeline failed for job=%s", job_id)
        raise HTTPException(
            status_code=500,
            detail=f"Compliance analysis failed: {exc}",
        )


@router.get("/compliance/health-check")
async def compliance_health() -> dict[str, Any]:
    """Verify Compliance pipeline agents are importable and graph compiles."""
    from app.agents.compliance.orchestrator import compliance_graph
    return {
        "data": {
            "status": "ok",
            "graph_nodes": (
                list(compliance_graph.nodes.keys())
                if hasattr(compliance_graph, "nodes")
                else []
            ),
            "agents": [
                "policies_agent",
                "violations_agent",
                "regulations_agent",
                "compliance_summary",
            ],
            "supported_frameworks": [
                "SOC2", "ISO 27001", "GDPR", "HIPAA",
                "PCI-DSS", "NIST CSF", "CCPA", "FedRAMP",
                "SOX", "CIS Controls",
            ],
        },
        "error": None,
    }
