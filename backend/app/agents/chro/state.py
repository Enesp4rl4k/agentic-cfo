"""
CHRO Agent State Definition

Defines the state structure for the Chief Human Resources Officer agent pipeline.
Three skill agents: headcount, attrition, compensation.
Orchestrator synthesizes into CHROState for CEO integration.
"""

from dataclasses import dataclass, field
from typing import Any, TypedDict


@dataclass
class CHROStepLog:
    """Log entry for CHRO pipeline execution."""
    node: str
    status: str  # "started" | "completed" | "failed"
    message: str
    metrics: dict[str, Any] | None = None


@dataclass
class CHROSkillResult:
    """Result from a CHRO skill (headcount, attrition, compensation)."""
    skill_name: str
    metrics: dict[str, Any]
    alerts: list[dict[str, str]]
    narrative: str | None = None
    error: str | None = None


@dataclass
class CHRORunConfig:
    """Configuration for CHRO pipeline run."""
    llm_enabled: bool = False
    settings: Any = None


class CHROState(TypedDict, total=False):
    """
    State for CHRO pipeline execution.
    
    Inputs (CSV data):
    - headcount_csv: Org structure, roles, levels, salary bands, locations
    - attrition_csv: Historical departures, reasons, tenure, replacement status
    - compensation_csv: Salary ranges, equity, benefits, market rates
    
    Outputs:
    - headcount: Analyzed headcount metrics (FTE, turnover rate, new hires)
    - attrition: Turnover analysis (churn by level/dept, cost of attrition)
    - compensation: Comp analysis (market alignment, equity burn, benefits cost)
    - chro_summary: Synthesized summary with risks and quick wins
    
    Internal:
    - logs: Step-by-step execution trace
    - error: Final error, if any
    """
    
    # Inputs
    headcount_csv: str
    attrition_csv: str
    compensation_csv: str
    company_name: str | None
    analysis_period: str | None
    
    # Outputs from skill agents
    headcount: dict[str, Any] | None
    attrition: dict[str, Any] | None
    compensation: dict[str, Any] | None
    
    # Synthesized output
    chro_summary: dict[str, Any] | None
    
    # Execution tracking
    logs: list[CHROStepLog] | None
    error: str | None
