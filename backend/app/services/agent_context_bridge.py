"""
Agent Context Bridge — CompanyContext → Agent Input enrichment.

FAZ-1B: Solves the "agents see only their own CSV" problem.

When an agent runs, this bridge:
  1. Loads the org's CompanyContext from Redis/DB
  2. Enriches the agent's input state with results from other agents
  3. Returns an enriched state dict ready for the agent pipeline

This gives every agent access to the full org intelligence:
  - CEO gets CFO + CTO + CMO signals
  - Risk agent knows about CFO anomalies
  - CHRO gets context from CFO (runway) and CTO (velocity)

Usage:
    from app.services.agent_context_bridge import enrich_state

    enriched = await enrich_state(
        agent="risk",
        base_state={"transactions": [...]},
        org_id=org_id,
        db=db,
    )
    result = await run_risk_pipeline(enriched)
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def enrich_state(
    agent: str,
    base_state: dict[str, Any],
    org_id: str,
    db: Any = None,
) -> dict[str, Any]:
    """
    Enrich the agent's input state with cross-domain data from CompanyContext.

    Returns a new dict (does not mutate base_state).
    Falls back to base_state unchanged if context is unavailable.
    """
    if not org_id:
        return base_state

    try:
        from app.services.company_context import get_company_context
        ctx = await get_company_context(org_id, db)
    except Exception as exc:
        logger.warning("Context bridge: failed to load context for org=%s: %s", org_id, exc)
        return base_state

    enriched = dict(base_state)

    # ── Inject CFO results (available to all agents) ──────────────────────────
    if ctx.last_cfo_result:
        cfo = ctx.last_cfo_result
        dashboard = cfo.get("dashboard") or cfo  # handle both formats

        # P&L, cashflow, forecast — used by Risk, Audit, CEO
        if dashboard.get("pnl") and "pnl" not in enriched:
            enriched["pnl"] = dashboard["pnl"]
        if dashboard.get("cashflow") and "cashflow" not in enriched:
            enriched["cashflow"] = dashboard["cashflow"]
        if dashboard.get("forecast") and "forecast" not in enriched:
            enriched["forecast"] = dashboard["forecast"]
        if cfo.get("anomalies") and "anomalies" not in enriched:
            enriched["anomalies"] = cfo["anomalies"]

        # Compact CFO summary for agents that don't need full data
        enriched["__cfo_summary"] = {
            "revenue":       (dashboard.get("pnl") or {}).get("revenue"),
            "net_margin":    (dashboard.get("pnl") or {}).get("net_margin"),
            "runway_months": _extract_runway(dashboard.get("forecast")),
            "critical_anomalies": _count_critical_anomalies(cfo.get("anomalies") or []),
        }

    # ── Inject CTO results (for CEO, CHRO cross-domain) ──────────────────────
    if ctx.last_cto_result and agent in ("ceo", "chro"):
        cto = ctx.last_cto_result
        enriched["__cto_summary"] = {
            "health_score":    (cto.get("cto_summary") or {}).get("overall_health_score"),
            "velocity_trend":  (cto.get("velocity") or {}).get("velocity_trend"),
            "debt_score":      (cto.get("tech_debt") or {}).get("debt_score"),
            "infra_waste_pct": _calc_waste_pct(cto.get("infra") or {}),
        }

    # ── Inject CMO results (for CEO cross-domain) ─────────────────────────────
    if ctx.last_cmo_result and agent == "ceo":
        cmo = ctx.last_cmo_result
        enriched["__cmo_summary"] = {
            "overall_roas": (cmo.get("campaigns") or {}).get("overall_roas"),
            "cac":          (cmo.get("campaigns") or {}).get("cac"),
        }

    # ── Inject CHRO results (for CEO cross-domain) ────────────────────────────
    if ctx.last_chro_result and agent == "ceo":
        chro = ctx.last_chro_result
        enriched["__chro_summary"] = {
            "turnover_rate":     (chro.get("workforce") or {}).get("turnover_rate"),
            "engagement_score":  (chro.get("engagement") or {}).get("score"),
            "headcount_change":  (chro.get("workforce") or {}).get("headcount_change"),
        }

    # ── Annotate with context metadata ───────────────────────────────────────
    enriched["__context_org_id"] = org_id
    enriched["__context_enriched"] = True

    logger.debug(
        "Context bridge: enriched state for agent=%s org=%s — keys added: %s",
        agent,
        org_id,
        [k for k in enriched if k not in base_state],
    )
    return enriched


def _extract_runway(forecast: dict | None) -> float | None:
    if not forecast:
        return None
    scenarios = forecast.get("scenarios") or {}
    base = scenarios.get("base") or {}
    return base.get("runway_months")


def _count_critical_anomalies(anomalies: list[dict]) -> int:
    return sum(1 for a in anomalies if a.get("severity") == "critical")


def _calc_waste_pct(infra: dict) -> float | None:
    total = infra.get("total_cost_cents")
    waste = infra.get("waste_estimate_cents")
    if total and waste and total > 0:
        return round(waste / total * 100, 1)
    return None
