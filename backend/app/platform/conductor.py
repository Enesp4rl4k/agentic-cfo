"""
Management Conductor — schedules role execution based on data availability and depth.

The conductor does NOT run agents itself; it produces an execution plan consumed by
auto_chain, ARQ workers, and the Command Center management layer.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.platform.contracts import AgentRole, RoleDepthLevel
from app.platform.policies import ROLE_DEFAULT_DEPTH

logger = logging.getLogger(__name__)

# Signals that unlock deeper execution per role
ROLE_DATA_SIGNALS: dict[AgentRole, tuple[str, ...]] = {
    AgentRole.CFO: ("cfo_job", "transactions", "file_upload"),
    AgentRole.RISK: ("cfo_result", "cashflow", "forecast"),
    AgentRole.CEO: ("cfo_result",),
    AgentRole.CTO: ("git_log", "cloud_billing", "incident_csv"),
    AgentRole.CMO: ("campaign_csv", "funnel_csv", "cohort_csv"),
    AgentRole.COO: ("sla_csv", "process_csv"),
    AgentRole.CHRO: ("headcount_csv", "attrition_csv"),
    AgentRole.AUDIT: ("cfo_result",),
    AgentRole.COMPLIANCE: ("cfo_result", "risk_result"),
    AgentRole.ACCOUNTING: ("transactions", "cfo_job"),
}


@dataclass
class RoleExecutionPlan:
    role: AgentRole
    depth_level: RoleDepthLevel
    should_run: bool
    reason: str
    queue: str = "analysis"  # analysis | maintenance


@dataclass
class ConductorPlan:
    org_id: str
    trigger: str
    roles: list[RoleExecutionPlan] = field(default_factory=list)

    def runnable_roles(self) -> list[AgentRole]:
        return [p.role for p in self.roles if p.should_run]

    def to_dict(self) -> dict[str, Any]:
        return {
            "org_id": self.org_id,
            "trigger": self.trigger,
            "roles": [
                {
                    "role": p.role.value,
                    "depth_level": p.depth_level,
                    "should_run": p.should_run,
                    "reason": p.reason,
                    "queue": p.queue,
                }
                for p in self.roles
            ],
        }


class ManagementConductor:
    """
    Produces a deterministic execution plan: which management roles run at what depth.

    Rules:
      1. Depth never exceeds ROLE_DEFAULT_DEPTH[role].
      2. Role runs only if at least one data signal is present (unless force=True).
      3. Risk/CEO auto-chain after CFO when cfo_result exists.
      4. Maintenance/backfill never blocks analysis queue (delegated to worker).
    """

    def plan(
        self,
        *,
        org_id: str,
        trigger: str,
        available_signals: set[str],
        force_roles: set[AgentRole] | None = None,
    ) -> ConductorPlan:
        force_roles = force_roles or set()
        plans: list[RoleExecutionPlan] = []

        for role in AgentRole:
            max_depth = ROLE_DEFAULT_DEPTH.get(role.value, 0)
            if max_depth == 0:
                continue

            signals = ROLE_DATA_SIGNALS.get(role, ())
            has_data = any(s in available_signals for s in signals)
            forced = role in force_roles

            if role in (AgentRole.CFO, AgentRole.RISK, AgentRole.CEO):
                queue = "analysis"
            else:
                queue = "analysis"

            if forced or has_data:
                depth: RoleDepthLevel = max_depth  # type: ignore[assignment]
                reason = "forced" if forced else f"signals={sorted(set(signals) & available_signals)}"
                plans.append(
                    RoleExecutionPlan(
                        role=role,
                        depth_level=depth,
                        should_run=True,
                        reason=reason,
                        queue=queue,
                    )
                )
            else:
                plans.append(
                    RoleExecutionPlan(
                        role=role,
                        depth_level=0,  # type: ignore[assignment]
                        should_run=False,
                        reason=f"missing signals for {role.value}",
                        queue=queue,
                    )
                )

        result = ConductorPlan(org_id=org_id, trigger=trigger, roles=plans)
        logger.debug(
            "Conductor plan org=%s trigger=%s runnable=%s",
            org_id,
            trigger,
            [r.value for r in result.runnable_roles()],
        )
        return result


def signals_from_company_context(context: dict[str, Any]) -> set[str]:
    """Derive available data signals from a CompanyContext-like dict (+ semantic metrics)."""
    signals: set[str] = set()
    if context.get("active_cfo_job_id") or context.get("last_cfo_result"):
        signals.update({"cfo_job", "cfo_result", "transactions"})
    if context.get("last_risk_result"):
        signals.add("risk_result")
    if context.get("last_cto_result"):
        signals.update({"git_log", "cloud_billing"})
    if context.get("last_cmo_result"):
        signals.update({"campaign_csv", "funnel_csv"})
    if context.get("last_chro_result"):
        signals.update({"headcount_csv", "attrition_csv"})
    if context.get("last_coo_result"):
        signals.update({"sla_csv", "process_csv"})

    # Metric presence unlocks roles even when CSV blobs are absent
    metrics = context.get("semantic_metrics") or context.get("__semantic_metrics") or {}
    if isinstance(metrics, dict):
        for mid in metrics:
            signals.add(f"metric:{mid}")
        if "finance.revenue" in metrics or "finance.runway_months" in metrics:
            signals.update({"cfo_result", "cashflow", "forecast"})
        if "growth.overall_roas" in metrics:
            signals.update({"campaign_csv", "funnel_csv"})
        if "tech.health_score" in metrics:
            signals.update({"git_log", "cloud_billing"})
        if "people.headcount" in metrics:
            signals.update({"headcount_csv", "attrition_csv"})
        if "ops.bottleneck_count" in metrics:
            signals.update({"sla_csv", "process_csv"})
        if "risk.overall_score" in metrics:
            signals.add("risk_result")
    return signals
