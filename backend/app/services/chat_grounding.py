"""Shared dual-RAG + semantic KPI grounding for chat surfaces."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.contracts import EvidenceBundle
from app.services.rag.grounding_validator import (
    apply_disclaimer,
    no_evidence_verdict,
    validate_grounding,
)


@dataclass
class GroundedChatPack:
    system_prompt: str
    evidence_found: bool
    evidence_tx_count: int
    evidence_semantic_count: int
    retriever_version: str
    semantic_values: dict[str, Any]
    evidence_bundle: EvidenceBundle | None = None
    grounding_flags: list[str] | None = None

    def to_meta(self) -> dict[str, Any]:
        return {
            "evidence_found": self.evidence_found,
            "evidence_tx_count": self.evidence_tx_count,
            "evidence_semantic_count": self.evidence_semantic_count,
            "evidence_retriever_version": self.retriever_version,
        }


async def prepare_grounded_chat(
    *,
    db: AsyncSession,
    org_id: str,
    question: str,
    base_system_prompt: str,
    job_id: str | None = None,
    locale: str = "tr",
) -> GroundedChatPack:
    """Attach dual RAG evidence + semantic KPIs to a chat system prompt."""
    from app.services.company_context import get_company_context
    from app.services.rag import retrieve_dual_evidence
    from app.services.semantic.store import (
        get_latest_semantic_snapshot,
        get_semantic_snapshot,
        resolve_period_key,
    )

    ctx = await get_company_context(org_id, db)
    active_job = job_id or (
        ctx.active_cfo_job_id if hasattr(ctx, "active_cfo_job_id") else None
    )

    evidence_bundle = await retrieve_dual_evidence(
        db=db,
        org_id=org_id,
        query=question,
        job_id=active_job,
        top_k_per_source=3,
    )
    evidence_block = evidence_bundle.to_prompt_block()
    evidence_found = evidence_bundle.found
    tx_sources = [c for c in evidence_bundle.citations if c.source_type == "cfo_transactions_raw"]
    semantic_sources = [
        c for c in evidence_bundle.citations if c.source_type == "semantic_snapshot"
    ]

    if not evidence_found:
        if locale.lower().startswith("tr"):
            evidence_block = (
                "## RAG Kanıtlar (evidence)\n"
                "- Bu soruya doğrudan kanıt bulunamadı. Yanıt verirken varsayımları açık belirt "
                "ve mümkünse kullanıcıdan veri/periyot netleştirmesi iste."
            )
        else:
            evidence_block = (
                "## RAG evidence\n"
                "- No direct evidence was found for this question. State assumptions clearly "
                "and ask the user to clarify data or period when needed."
            )

    semantic_block = ""
    semantic_values: dict[str, Any] = {}
    try:
        period = resolve_period_key(ctx.reporting_period)
        snap = await get_semantic_snapshot(org_id, period.key, db)
        if snap is None:
            snap = await get_latest_semantic_snapshot(org_id, db)
        if snap is not None:
            semantic_values = snap.values()
            lines = [
                f"## Semantic KPIs (period={snap.period.key}, currency={snap.currency})",
            ]
            for mid, val in list(semantic_values.items())[:20]:
                conf = snap.metric_map()[mid].confidence if mid in snap.metric_map() else 1.0
                lines.append(f"- {mid} = {val} (confidence={conf:.2f})")
            if snap.brief:
                lines.append(f"- decision_brief.headline = {snap.brief.headline}")
                lines.append(f"- decision_brief.health_score = {snap.brief.health_score}")
            semantic_block = "\n".join(lines)
    except Exception:
        pass

    parts = [base_system_prompt]
    if semantic_block:
        parts.append(semantic_block)
    if evidence_block:
        parts.append(evidence_block)

    return GroundedChatPack(
        system_prompt="\n\n".join(parts),
        evidence_found=evidence_found,
        evidence_tx_count=len(tx_sources),
        evidence_semantic_count=len(semantic_sources),
        retriever_version=evidence_bundle.retriever_version,
        semantic_values=semantic_values,
        evidence_bundle=evidence_bundle,
    )


def finalize_grounded_answer(
    answer: str,
    pack: GroundedChatPack,
    *,
    locale: str = "tr",
) -> tuple[str, bool]:
    """Apply grounding validator + no-evidence disclaimer. Returns (text, validated)."""
    if not pack.evidence_found and not pack.semantic_values:
        verdict = no_evidence_verdict()
        pack.grounding_flags = list(verdict.flagged_claims)
        return apply_disclaimer(answer, verdict, locale=locale), False

    grounding = validate_grounding(
        answer,
        pack.evidence_bundle if pack.evidence_found else None,
        semantic_metrics=pack.semantic_values or None,
    )
    pack.grounding_flags = list(grounding.flagged_claims)
    if grounding.requires_disclaimer:
        return apply_disclaimer(answer, grounding, locale=locale), False
    return answer, True
