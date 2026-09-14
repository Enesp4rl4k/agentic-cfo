"""
Independent verifier node — grades agent output without producing it.

Project law: the skill that computed a result must not be the one that verifies it.
This module implements rule-based verification (reflection scores, confidence,
fatal errors). LLM-based verification can be added as a separate subgraph later.
"""

from __future__ import annotations

import logging
from typing import Any

from app.agents.state import AgentRunConfig, CFOState, StepLog
from app.platform.contracts import VerifierVerdict
from app.platform.policies import (
    CONFIDENCE_AUTO_PROCEED_MIN,
    REFLECTION_HOLD_THRESHOLD,
    REFLECTION_WARN_THRESHOLD,
)

logger = logging.getLogger(__name__)

_REFLECTION_AGENTS = ("pnl", "cashflow", "forecast")


def evaluate_cfo_state(
    state: CFOState,
    *,
    run_config: AgentRunConfig | None = None,
) -> VerifierVerdict:
    """
    Rule-based verifier for CFO pipeline state.
    Returns proceed | hold_for_review | halt.
    """
    cfg = run_config or AgentRunConfig()

    if state.get("halted"):
        return VerifierVerdict(
            action="halt",
            reasons=[state.get("error") or "pipeline halted"],
            confidence=0.0,
        )

    # ── Hard hold conditions — NEVER bypassable (CLAUDE.md Law #10) ───────────
    # `require_review` may only suppress the soft heuristic warnings below; a
    # low-confidence result or a skill that explicitly asked for review always
    # routes to a human.
    hard_reasons: list[str] = []
    soft_reasons: list[str] = []
    reflection_failures: list[str] = []

    # Effective threshold comes from the run config (defaults to the platform
    # policy). Setting it to 0.0 is a legitimate "accept any confidence" run,
    # not a bypass — the gate still evaluates, it just evaluates to proceed.
    effective_min = (
        cfg.auto_proceed_min_confidence
        if cfg.auto_proceed_min_confidence is not None
        else CONFIDENCE_AUTO_PROCEED_MIN
    )
    min_conf = float(state.get("min_confidence") or 1.0)
    if min_conf < effective_min:
        hard_reasons.append(f"min_confidence {min_conf:.2f} < {effective_min:.2f}")

    if state.get("awaiting_review"):
        hard_reasons.append("skill flagged needs_review / awaiting_review")

    reflection_scores = state.get("reflection_scores") or {}
    for agent in _REFLECTION_AGENTS:
        entry = reflection_scores.get(agent) or {}
        score = entry.get("overall_score")
        if score is None:
            continue
        try:
            score_f = float(score)
        except (TypeError, ValueError):
            continue
        if score_f < REFLECTION_HOLD_THRESHOLD:
            reflection_failures.append(f"{agent}:{score_f:.2f}")
        elif score_f < REFLECTION_WARN_THRESHOLD:
            soft_reasons.append(f"reflection warn {agent}={score_f:.2f}")

    if reflection_failures:
        hard_reasons.append(
            "reflection below hold threshold: " + ", ".join(reflection_failures)
        )

    if hard_reasons:
        return VerifierVerdict(
            action="hold_for_review",
            reasons=hard_reasons + soft_reasons,
            confidence=min_conf,
            reflection_failures=reflection_failures,
        )

    if soft_reasons:
        if cfg.require_review:
            return VerifierVerdict(
                action="hold_for_review",
                reasons=soft_reasons,
                confidence=min_conf,
            )
        logger.info(
            "Verifier: soft warnings only, require_review=False — proceeding (%s)",
            soft_reasons,
        )
        return VerifierVerdict(
            action="proceed", reasons=soft_reasons, confidence=min_conf
        )

    return VerifierVerdict(action="proceed", confidence=min_conf)


async def node_verifier(state: CFOState, config: dict) -> CFOState:
    """LangGraph node wrapper — patches state based on verifier verdict."""
    from app.agents.orchestrator import (
        _run_config,  # lazy import avoids cycle at module load
    )

    cfg = _run_config(config)
    verdict = evaluate_cfo_state(state, run_config=cfg)

    from app.agents.confidence_breakdown import build_confidence_breakdown

    effective_min = (
        cfg.auto_proceed_min_confidence
        if cfg.auto_proceed_min_confidence is not None
        else CONFIDENCE_AUTO_PROCEED_MIN
    )
    breakdown = build_confidence_breakdown(state, threshold=effective_min)

    existing_logs = list(state.get("logs") or [])
    existing_logs.append(
        StepLog(
            step="verifier",
            ok=verdict.action == "proceed",
            detail="; ".join(verdict.reasons) or "passed",
            confidence=verdict.confidence,
        )
    )
    min_conf = state.get("min_confidence", 1.0)
    if verdict.confidence is not None:
        min_conf = min(min_conf, verdict.confidence)

    patch: dict[str, Any] = {
        "logs": existing_logs,
        "min_confidence": min_conf,
        "confidence_breakdown": breakdown,
        "verifier_verdict": {
            "action": verdict.action,
            "reasons": verdict.reasons,
            "reflection_failures": verdict.reflection_failures,
            "confidence": verdict.confidence,
            "confidence_breakdown": breakdown,
        },
    }
    if verdict.should_hold:
        patch["awaiting_review"] = True
    return {**state, **patch}  # type: ignore[return-value,typeddict-item]
