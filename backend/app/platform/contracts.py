"""
Platform contracts — typed handoffs between roles, RAG, and verification.

These types are domain-neutral and stable; orchestrators map their state into them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal, TypedDict


class AgentRole(str, Enum):
    CFO = "cfo"
    CEO = "ceo"
    CTO = "cto"
    CMO = "cmo"
    COO = "coo"
    CHRO = "chro"
    RISK = "risk"
    AUDIT = "audit"
    COMPLIANCE = "compliance"
    ACCOUNTING = "accounting"


RoleDepthLevel = Literal[0, 1, 2, 3]
VerifierAction = Literal["proceed", "hold_for_review", "halt"]


@dataclass(frozen=True)
class EvidenceCitation:
    """Structured citation for UI and hallucination checks."""

    job_id: str | None
    chunk_index: int
    source_type: str
    score: float
    preview: str
    char_start: int | None = None
    char_end: int | None = None


@dataclass
class EvidenceBundle:
    """Retrieved evidence pack passed to chat / synthesis nodes."""

    query: str
    org_id: str
    citations: list[EvidenceCitation] = field(default_factory=list)
    job_scope: str = "org_wide"  # job_scoped | org_wide
    retriever_version: str = "tfidf_v1"

    @property
    def found(self) -> bool:
        return len(self.citations) > 0

    def to_prompt_block(self) -> str:
        if not self.citations:
            return ""
        lines = ["## RAG Kanıtlar (evidence)"]
        for c in self.citations:
            jid = c.job_id or "(unknown-job)"
            lines.append(
                f"- job={jid} chunk={c.chunk_index} "
                f"source={c.source_type} score={c.score:.2f}: {c.preview}"
            )
        return "\n".join(lines)


@dataclass
class VerifierVerdict:
    """
    Output of the independent verifier node — never produced by the same skill
    that generated the financial narrative.
    """

    action: VerifierAction
    reasons: list[str] = field(default_factory=list)
    confidence: float = 1.0
    reflection_failures: list[str] = field(default_factory=list)

    @property
    def should_hold(self) -> bool:
        return self.action == "hold_for_review"

    @property
    def should_halt(self) -> bool:
        return self.action == "halt"


class PlatformHandoff(TypedDict, total=False):
    """
    Cross-role state handoff written to CompanyContext after each agent run.
    Versioned schema for management layer consumers.
    """

    schema_version: str  # e.g. platform_handoff_v1
    org_id: str
    role: str
    job_id: str
    depth_level: RoleDepthLevel
    confidence: float
    awaiting_review: bool
    summary: dict[str, Any]
    evidence_bundle_id: str | None
    produced_at: str  # ISO UTC
