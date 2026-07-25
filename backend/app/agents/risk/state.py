"""
Risk Agent State Definition

Enterprise operational risk management: risk register analysis, loss event tracking,
and key risk indicator (KRI) monitoring.

Three skill agents:
  - register_agent:   Risk register — likelihood/impact scoring, risk heatmap
  - loss_agent:       Loss events — incident cost tracking, frequency analysis
  - kri_agent:        Key Risk Indicators — threshold breach detection, trend
Orchestrator synthesises into RiskState for CEO integration.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, TypedDict


@dataclass
class RiskStepLog:
    """Log entry for Risk pipeline execution."""
    node: str
    status: str          # "started" | "completed" | "failed"
    message: str
    metrics: dict[str, Any] | None = None


@dataclass
class RiskSkillResult:
    """Result from a Risk skill agent."""
    skill_name: str
    metrics: dict[str, Any]
    alerts: list[dict[str, str]]
    narrative: str | None = None
    error: str | None = None


@dataclass
class RiskRunConfig:
    """Configuration for Risk pipeline run."""
    llm_enabled: bool = False
    settings: Any = None


class RiskState(TypedDict, total=False):
    """
    State for Risk pipeline execution.

    Inputs (CSV data):
    - register_csv  : Risk ID | category | description | likelihood (1-5) |
                      impact (1-5) | owner | status | mitigation
    - loss_csv      : Date | category | description | gross_loss | recovery |
                      root_cause | status
    - kri_csv       : KRI name | category | current_value | threshold_red |
                      threshold_amber | unit | trend | owner

    Outputs:
    - register  : Risk heatmap, top risks, residual risk score
    - losses    : Total loss, frequency, top loss categories
    - kris      : KRI breaches, trending KRIs, composite KRI score
    - risk_summary : Synthesised enterprise risk score, top risks, quick wins
    """

    # ── Inputs ──────────────────────────────────────────────────────────────
    register_csv: str
    loss_csv: str
    kri_csv: str
    company_name: str | None
    reporting_period: str | None

    # ── Skill outputs ────────────────────────────────────────────────────────
    register: dict[str, Any] | None
    losses: dict[str, Any] | None
    kris: dict[str, Any] | None

    # ── Synthesised output ───────────────────────────────────────────────────
    risk_summary: dict[str, Any] | None

    # ── Execution tracking ───────────────────────────────────────────────────
    logs: list[RiskStepLog] | None
    error: str | None
