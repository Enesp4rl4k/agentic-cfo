"""
Cross-Context Enricher — S2: Sprint 2 shared utility.

Every C-Suite orchestrator calls this at startup to inject cross-domain
signals into their initial state. The enricher pulls data from
CompanyContext (Redis/DB) and formats it as `__context_*` keys.

Agent summary nodes read these keys when building LLM prompts,
giving every agent awareness of what other agents have found.

Pattern:
    enriched = await enrich_initial_state("chro", base_state, org_id)
    # enriched now has __cfo_summary, __cto_summary, etc.

Design:
  - Non-fatal: if context unavailable, returns base_state unchanged
  - Lazy: only loads context keys relevant to the requesting agent
  - Thin: adds summary keys only, never full result payloads
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Which context keys each agent cares about
_AGENT_CONTEXT_MAP: dict[str, list[str]] = {
    "cto":        ["__cfo_summary", "__chro_summary"],
    "chro":       ["__cfo_summary", "__cto_summary"],
    "cmo":        ["__cfo_summary", "__coo_summary"],
    "coo":        ["__cto_summary", "__chro_summary"],
    "compliance": ["__cfo_summary"],  # muhasebe anomalileri
    "audit":      ["__cfo_summary"],  # anomaly cross-check
    "risk":       ["__cfo_summary", "__cto_summary"],
    "ceo":        ["__cfo_summary", "__cto_summary", "__cmo_summary", "__chro_summary"],
}


async def enrich_initial_state(
    agent: str,
    base_state: dict[str, Any],
    org_id: str | None,
) -> dict[str, Any]:
    """
    Enrich the initial state dict with cross-domain context from CompanyContext.

    Returns a new dict (never mutates base_state).
    Safe to call even when org_id is None or context is unavailable.
    """
    if not org_id:
        return base_state

    try:
        from app.services.agent_context_bridge import enrich_state
        bridge = await enrich_state(agent, base_state, org_id=org_id)
        # Only include keys this agent actually needs
        relevant_keys = _AGENT_CONTEXT_MAP.get(agent, [])
        extra = {k: v for k, v in bridge.items() if k in relevant_keys and v is not None}
        if extra:
            logger.debug("Cross-context enriched agent=%s keys=%s", agent, list(extra))
        return {**base_state, **extra}
    except Exception as exc:
        logger.debug("Cross-context enrichment failed (non-fatal): agent=%s err=%s", agent, exc)
        return base_state


def build_cross_context_prompt_block(state: dict[str, Any], agent: str) -> str:
    """
    Format all cross-context keys from state into a human-readable prompt block.

    Used inside LLM summary nodes to append cross-domain signals.
    Returns empty string if no context available.
    """
    lines: list[str] = []

    # CFO context
    cfo = state.get("__cfo_summary") or {}
    if cfo:
        if cfo.get("runway_months") is not None:
            runway = cfo["runway_months"]
            risk_note = " ⚠️ KRİTİK" if runway < 6 else ""
            lines.append(f"Nakit Ömrü (CFO): {runway:.1f} ay{risk_note}")
        if cfo.get("net_margin") is not None:
            lines.append(f"Net Kâr Marjı (CFO): %{cfo['net_margin']*100:.1f}")
        if cfo.get("critical_anomalies"):
            lines.append(f"CFO Kritik Anomali: {cfo['critical_anomalies']} adet")
        if cfo.get("revenue") is not None:
            lines.append(f"Gelir (CFO): ₺{cfo['revenue']/100:,.0f}")

    # CTO context
    cto = state.get("__cto_summary") or {}
    if cto:
        if cto.get("health_score") is not None:
            lines.append(f"Teknoloji Sağlık Skoru (CTO): {cto['health_score']:.1f}/10")
        if cto.get("velocity_trend"):
            lines.append(f"Mühendis Velocity Trendi (CTO): {cto['velocity_trend']}")
        if cto.get("infra_waste_pct") is not None:
            lines.append(f"Altyapı İsraf Oranı (CTO): %{cto['infra_waste_pct']:.0f}")

    # CMO context
    cmo = state.get("__cmo_summary") or {}
    if cmo:
        if cmo.get("overall_roas") is not None:
            lines.append(f"Pazarlama ROAS (CMO): {cmo['overall_roas']:.1f}x")
        if cmo.get("cac") is not None:
            lines.append(f"Müşteri Edinme Maliyeti (CMO): ₺{cmo['cac']/100:,.0f}")

    # CHRO context
    chro = state.get("__chro_summary") or {}
    if chro:
        if chro.get("turnover_rate") is not None:
            tr = chro["turnover_rate"]
            risk_note = " ⚠️ YÜKSEK" if tr > 0.15 else ""
            lines.append(f"İşten Ayrılma Oranı (CHRO): %{tr*100:.0f}{risk_note}")
        if chro.get("headcount_change") is not None:
            lines.append(f"Kadro Değişimi (CHRO): {chro['headcount_change']:+d} kişi")
        if chro.get("engagement_score") is not None:
            lines.append(f"Çalışan Bağlılık Skoru (CHRO): {chro['engagement_score']:.0f}/100")

    # COO context
    coo = state.get("__coo_summary") or {}
    if coo:
        if coo.get("sla_compliance") is not None:
            lines.append(f"SLA Uyumu (COO): %{coo['sla_compliance']*100:.0f}")

    if not lines:
        return ""

    return "\n\nÇapraz Domain Bağlamı:\n" + "\n".join(f"• {line}" for line in lines)
