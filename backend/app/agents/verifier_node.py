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
    reasons: list[str] = []
    reflection_failures: list[str] = []

    if state.get("halted"):
        return VerifierVerdict(
            action="halt",
            reasons=[state.get("error") or "pipeline halted"],
            confidence=0.0,
        )

    min_conf = float(state.get("min_confidence") or 1.0)
    if min_conf < CONFIDENCE_AUTO_PROCEED_MIN:
        reasons.append(f"min_confidence {min_conf:.2f} < {CONFIDENCE_AUTO_PROCEED_MIN}")

    if state.get("awaiting_review"):
        reasons.append("skill flagged awaiting_review")

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
            reasons.append(f"reflection warn {agent}={score_f:.2f}")

    if reflection_failures:
        reasons.append(
            "reflection below hold threshold: " + ", ".join(reflection_failures)
        )

    # Check step logs for explicit needs_review from skills
    logs: list[Any] = state.get("logs") or []
    for log in logs:
        if isinstance(log, StepLog):
            step_name = log.step
        elif isinstance(log, dict):
            step_name = str(log.get("step", ""))
        else:
            continue
        if step_name in ("review_gate", "verifier"):
            continue

    if reasons or reflection_failures:
        action = "hold_for_review" if cfg.require_review else "proceed"
        if not cfg.require_review:
            logger.warning(
                "Verifier would hold (%s) but require_review=False — proceeding",
                reasons + reflection_failures,
            )
        return VerifierVerdict(
            action=action,
            reasons=reasons,
            confidence=min_conf,
            reflection_failures=reflection_failures,
        )

    return VerifierVerdict(action="proceed", confidence=min_conf)


async def node_verifier(state: CFOState, config: dict) -> CFOState:
    """LangGraph node wrapper — patches state based on verifier verdict."""
    from app.agents.orchestrator import _run_config  # lazy import avoids cycle at module load

    verdict = evaluate_cfo_state(state, run_config=_run_config(config))
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
        "verifier_verdict": {
            "action": verdict.action,
            "reasons": verdict.reasons,
            "reflection_failures": verdict.reflection_failures,
            "confidence": verdict.confidence,
        },
    }
    if verdict.should_hold:
        patch["awaiting_review"] = True
    return {**state, **patch}  # type: ignore[return-value]
