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

# ── Queue & execution ─────────────────────────────────────────────────────────
AGENT_JOB_TIMEOUT_ANALYSIS_SECONDS: int = 600
AGENT_JOB_TIMEOUT_MAINTENANCE_SECONDS: int = 1200
AGENT_MAX_TRIES: int = 2
