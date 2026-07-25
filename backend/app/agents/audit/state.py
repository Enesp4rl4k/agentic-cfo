"""
Internal Audit Agent State Definition

Enterprise internal audit management: audit findings, control effectiveness,
and audit universe coverage tracking.

Three skill agents:
  - findings_agent   : Audit findings — severity, status, overdue remediations
  - controls_agent   : Control effectiveness — design/operating effectiveness scores
  - coverage_agent   : Audit universe — coverage rate, auditable units, scheduling gaps
Orchestrator synthesises into AuditState for CEO integration.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any, TypedDict


@dataclass
class AuditStepLog:
    node: str
    status: str          # "started" | "completed" | "failed"
    message: str
    metrics: dict[str, Any] | None = None


@dataclass
class AuditSkillResult:
    skill_name: str
    metrics: dict[str, Any]
    alerts: list[dict[str, str]]
    narrative: str | None = None
    error: str | None = None


class AuditState(TypedDict, total=False):
    """
    State for Internal Audit pipeline.

    Inputs (CSV):
    - findings_csv  : Finding ID | title | severity | status | due_date |
                      owner | category | remediation_status
    - controls_csv  : Control ID | name | category | design_effectiveness |
                      operating_effectiveness | last_tested | owner
    - coverage_csv  : Unit name | category | last_audit | frequency |
                      risk_rating | scheduled_next
    """

    # ── Inputs ────────────────────────────────────────────────────────────────
    findings_csv: str
    controls_csv: str
    coverage_csv: str
    company_name: str | None
    audit_period: str | None

    # ── Skill outputs ─────────────────────────────────────────────────────────
    findings: dict[str, Any] | None
    controls: dict[str, Any] | None
    coverage: dict[str, Any] | None

    # ── Synthesised output ────────────────────────────────────────────────────
    audit_summary: dict[str, Any] | None

    # ── Execution tracking ────────────────────────────────────────────────────
    logs: list[AuditStepLog] | None
    error: str | None
