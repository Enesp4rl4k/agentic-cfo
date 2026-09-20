"""
Agent Context Bridge — CompanyContext + Semantic Model → Agent Input enrichment.

FAZ-1B: Solves the "agents see only their own CSV" problem.
Semantic layer: prefers typed metrics when a snapshot exists.
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
    Enrich the agent's input state with cross-domain data from CompanyContext
    and the canonical semantic snapshot when available.
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

    # ── Semantic metrics (preferred) ──────────────────────────────────────────
    semantic_values: dict[str, Any] = {}
    try:
        from app.services.semantic.store import (
            get_latest_semantic_snapshot,
            get_semantic_snapshot,
            resolve_period_key,
        )

        period = resolve_period_key(ctx.reporting_period)
        snap = await get_semantic_snapshot(org_id, period.key, db)
        if snap is None:
            snap = await get_latest_semantic_snapshot(org_id, db)
        if snap is not None:
            semantic_values = snap.values()
            enriched["__semantic_metrics"] = semantic_values
            enriched["__semantic_period"] = snap.period.key
            enriched["__semantic_currency"] = snap.currency
            enriched["__semantic_locale"] = snap.locale
            if snap.brief:
                enriched["__decision_brief"] = snap.brief.to_dict()
    except Exception as exc:
        logger.debug("Context bridge: semantic load skipped: %s", exc)

    # ── Inject CFO results (available to all agents) ──────────────────────────
    if ctx.last_cfo_result:
        cfo = ctx.last_cfo_result
        dashboard = cfo.get("dashboard") or cfo

        if dashboard.get("pnl") and "pnl" not in enriched:
            enriched["pnl"] = dashboard["pnl"]
        if dashboard.get("cashflow") and "cashflow" not in enriched:
            enriched["cashflow"] = dashboard["cashflow"]
        if dashboard.get("forecast") and "forecast" not in enriched:
            enriched["forecast"] = dashboard["forecast"]
        if cfo.get("anomalies") and "anomalies" not in enriched:
            enriched["anomalies"] = cfo["anomalies"]

        enriched["__cfo_summary"] = {
            "revenue": semantic_values.get(
                "finance.revenue",
                (dashboard.get("pnl") or {}).get("revenue"),
            ),
            "net_margin": semantic_values.get(
                "finance.net_margin",
                (dashboard.get("pnl") or {}).get("net_margin"),
            ),
            "runway_months": semantic_values.get(
                "finance.runway_months",
                _extract_runway(dashboard.get("forecast")),
            ),
            "critical_anomalies": semantic_values.get(
                "finance.critical_anomalies",
                _count_critical_anomalies(cfo.get("anomalies") or []),
            ),
        }

    # ── Inject CTO results (for CEO, CHRO cross-domain) ──────────────────────
    if ctx.last_cto_result and agent in ("ceo", "chro"):
        cto = ctx.last_cto_result
        enriched["__cto_summary"] = {
            "health_score": semantic_values.get(
                "tech.health_score",
                (cto.get("cto_summary") or {}).get("overall_health_score"),
            ),
            "velocity_trend": semantic_values.get(
                "tech.velocity_trend",
                (cto.get("velocity") or {}).get("velocity_trend"),
            ),
            "debt_score": semantic_values.get(
                "tech.debt_score",
                (cto.get("tech_debt") or {}).get("debt_score"),
            ),
            "infra_waste_pct": semantic_values.get(
                "tech.infra_waste_pct",
                _calc_waste_pct(cto.get("infra") or {}),
            ),
        }

    # ── Inject CMO results (for CEO cross-domain) ─────────────────────────────
    if ctx.last_cmo_result and agent == "ceo":
        cmo = ctx.last_cmo_result
        enriched["__cmo_summary"] = {
            "overall_roas": semantic_values.get(
                "growth.overall_roas",
                (cmo.get("campaigns") or {}).get("overall_roas"),
            ),
            "cac": semantic_values.get(
                "growth.blended_cac",
                (cmo.get("campaigns") or {}).get("cac"),
            ),
        }

    # ── Inject CHRO results (for CEO cross-domain) ────────────────────────────
    if ctx.last_chro_result and agent == "ceo":
        chro = ctx.last_chro_result
        enriched["__chro_summary"] = {
            "turnover_rate": semantic_values.get(
                "people.turnover_rate",
                (chro.get("workforce") or {}).get("turnover_rate"),
            ),
            "engagement_score": (chro.get("engagement") or {}).get("score"),
            "headcount_change": (chro.get("workforce") or {}).get("headcount_change"),
            "headcount": semantic_values.get("people.headcount"),
            "attrition_rate": semantic_values.get("people.attrition_rate"),
        }

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
