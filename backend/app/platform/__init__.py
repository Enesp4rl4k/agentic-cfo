"""
Platform engineering layer — shared contracts, policies, and conductor for
multi-role agentic + RAG systems.

Import from here for cross-cutting types; avoid duplicating magic numbers in agents.
"""

from app.platform.contracts import (
    AgentRole,
    EvidenceBundle,
    EvidenceCitation,
    PlatformHandoff,
    RoleDepthLevel,
    VerifierVerdict,
)
from app.platform.policies import (
    CONFIDENCE_AUTO_PROCEED_MIN,
    RAG_DEFAULT_CANDIDATE_LIMIT,
    RAG_DEFAULT_TOP_K,
    REFLECTION_HOLD_THRESHOLD,
)

__all__ = [
    "AgentRole",
    "EvidenceBundle",
    "EvidenceCitation",
    "PlatformHandoff",
    "RoleDepthLevel",
    "VerifierVerdict",
    "CONFIDENCE_AUTO_PROCEED_MIN",
    "RAG_DEFAULT_CANDIDATE_LIMIT",
    "RAG_DEFAULT_TOP_K",
    "REFLECTION_HOLD_THRESHOLD",
]
