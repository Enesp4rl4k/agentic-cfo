"""
Engineering policies — single source of truth for agentic + RAG thresholds.

All agents, workers, and API layers MUST import from here instead of hardcoding.
"""

from __future__ import annotations

# ── Confidence & human review ─────────────────────────────────────────────────
CONFIDENCE_AUTO_PROCEED_MIN: float = 0.80
REFLECTION_HOLD_THRESHOLD: float = 0.55
REFLECTION_WARN_THRESHOLD: float = 0.70

# ── RAG retrieval ─────────────────────────────────────────────────────────────
RAG_DEFAULT_TOP_K: int = 5
RAG_DEFAULT_CANDIDATE_LIMIT: int = 120
RAG_MIN_SCORE: float = 0.06
RAG_CHUNK_MAX_CHARS: int = 1800
RAG_CHUNK_OVERLAP_CHARS: int = 200
RAG_EVIDENCE_CACHE_TTL_SECONDS: float = 45.0
RAG_EVIDENCE_CACHE_MAX_ENTRIES: int = 512

# Known source types (extend as domain outputs are indexed)
RAG_SOURCE_CFO_RAW: str = "cfo_transactions_raw"
RAG_SOURCE_CFO_REPORT: str = "cfo_dashboard_json"
RAG_SOURCE_DOMAIN_PREFIX: str = "domain_"  # domain_{role}_{job_id}

# ── Role depth (management layer maturity) ────────────────────────────────────
# L0 = lens/KPI, L1 = structured agent, L2 = kernel+cross-role, L3 = autopilot
#
# PROVENANCE CAP: cto / cmo / chro / coo have no dedicated data source. Without a
# connected integration or pasted CSV their kernels *synthesise* metrics from CFO
# financials x fixed sector benchmarks (data_source "estimated"/"benchmark"; see
# app/platform/provenance.py). Such results are labelled synthetic in the API,
# badged in the UI, and are NOT allowed to drive downstream automation
# (app/agents/orchestration/auto_chain.py). These roles therefore stay at L1 and
# cannot be promoted toward autopilot until a real data source makes their
# figures "real".
ROLE_DEFAULT_DEPTH: dict[str, int] = {
    "cfo": 2,
    "risk": 2,
    "ceo": 2,
    "audit": 1,
    "compliance": 1,
    "coo": 1,
    "cto": 1,
    "cmo": 1,
    "chro": 1,
}

# Depth of concrete verticals (a vertical composes several roles end-to-end).
# Only the TR accounting vertical is L3: it runs file → CFO pipeline → TR
# accounting → board deck unattended, stopping at one consolidated approval gate
# (app/agents/tr_vertical.py). Everything else stays at its ROLE_DEFAULT_DEPTH;
# deepening a second vertical is deliberate future work, not a default.
PLATFORM_DEPTH: dict[str, int] = {
    "tr_accounting_vertical": 3,
    **ROLE_DEFAULT_DEPTH,
}
MAX_AUTOPILOT_DEPTH: int = 3

# ── Queue & execution ─────────────────────────────────────────────────────────
AGENT_JOB_TIMEOUT_ANALYSIS_SECONDS: int = 600
AGENT_JOB_TIMEOUT_MAINTENANCE_SECONDS: int = 1200
AGENT_MAX_TRIES: int = 2

# ── Model Gateway (single LLM egress point) ───────────────────────────────────
# Every LLM call in the backend goes through app.platform.model_gateway.complete.
LLM_CALL_TIMEOUT_SECONDS: float = 45.0
LLM_CALL_MAX_ATTEMPTS: int = 2
LLM_CALL_BACKOFF_BASE_SECONDS: float = 0.75
LLM_CACHE_TTL_SECONDS: float = 300.0
LLM_CACHE_MAX_ENTRIES: int = 512

# ── Per-org LLM budget (USD) ─────────────────────────────────────────────────
# Rolling window = current calendar month. Spend is measured from LLMCallLog.
# 0 / None on an org means "use the default". A hard-cap breach raises
# LLMBudgetExceeded before the call leaves the process.
LLM_ORG_MONTHLY_BUDGET_USD_DEFAULT: float = 50.0
LLM_ORG_BUDGET_SOFT_WARN_RATIO: float = 0.80   # log a warning past 80 % of budget
LLM_ORG_BUDGET_CHECK_TTL_SECONDS: float = 60.0  # cache the per-org spend lookup
