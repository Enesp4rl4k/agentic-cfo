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
