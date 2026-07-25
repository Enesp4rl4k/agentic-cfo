"""
Compliance Agent State Definition

Tracks regulatory compliance, policy adherence, and governance controls.
Three skill agents: policies, violations, regulations.
Orchestrator synthesizes into ComplianceState for CEO integration.
"""

from dataclasses import dataclass, field
from typing import Any, TypedDict


@dataclass
class ComplianceStepLog:
    """Log entry for Compliance pipeline execution."""
    node: str
    status: str  # "started" | "completed" | "failed"
    message: str
    metrics: dict[str, Any] | None = None


@dataclass
class ComplianceSkillResult:
    """Result from a Compliance skill (policies, violations, regulations)."""
    skill_name: str
    metrics: dict[str, Any]
    alerts: list[dict[str, str]]
    narrative: str | None = None
    error: str | None = None


@dataclass
class ComplianceRunConfig:
    """Configuration for Compliance pipeline run."""
    llm_enabled: bool = False
    settings: Any = None


class ComplianceState(TypedDict, total=False):
    """
    State for Compliance pipeline execution.
    
    Inputs (CSV data):
    - policy_csv: Policy name, severity, status, last_review, owner
    - violations_csv: Violation, policy_id, date_found, remediation_status, responsible_party
    - regulations_csv: Regulation, requirement, compliance_method, last_audit, owner
    
    Outputs:
    - policies: Policy inventory and compliance status
    - violations: Active/overdue violations tracking
    - regulations: Regulatory compliance status
    - compliance_summary: Synthesized compliance health score and risks
    
    Internal:
    - logs: Step-by-step execution trace
    - error: Final error, if any
    """
    
    # Inputs
    policy_csv: str
    violations_csv: str
    regulations_csv: str
    company_name: str | None
    audit_period: str | None
    
    # Outputs from skill agents
    policies: dict[str, Any] | None
    violations: dict[str, Any] | None
    regulations: dict[str, Any] | None
    
    # Synthesized output
    compliance_summary: dict[str, Any] | None
    
    # Execution tracking
    logs: list[ComplianceStepLog] | None
    error: str | None
