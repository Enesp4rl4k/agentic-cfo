"""
Reflection-Guided Retry — FAZ-4A.

Wraps an async LLM call with automatic evaluation and retry.

If the first response fails the ReflectionAgent quality threshold,
it retries with the improvement hints injected into the prompt.
Up to max_retries attempts (default: 2).

Usage:
    from app.services.retry_with_reflection import reflect_and_retry

    narrative = await reflect_and_retry(
        call_fn=lambda hint: llm.ainvoke(build_prompt(state, hint)),
        evaluate_fn=lambda text: reflection_agent.evaluate_pnl_narrative(text, pnl),
        label="pnl_narrative",
    )
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)

# Minimum score to accept without retrying
_DEFAULT_THRESHOLD = 0.60
# Maximum retry attempts after the initial call
_DEFAULT_MAX_RETRIES = 2


async def reflect_and_retry(
    call_fn: Callable[[str | None], Awaitable[Any]],
    evaluate_fn: Callable[[str], Any],
    label: str = "agent",
    max_retries: int = _DEFAULT_MAX_RETRIES,
    threshold: float = _DEFAULT_THRESHOLD,
    extract_text: Callable[[Any], str] | None = None,
) -> str:
    """
    Call an LLM function, evaluate the result, retry with feedback if needed.

    Parameters
    ----------
    call_fn : async (improvement_hint: str | None) -> response
        Called with None on first attempt; called with hint string on retries.
    evaluate_fn : (text: str) -> ReflectionResult
        Called after each attempt to score the output.
    label : str
        Human-readable label for log messages.
    max_retries : int
        Maximum additional attempts after the first (default 2 → up to 3 total).
    threshold : float
        Minimum score to accept without retrying.
    extract_text : callable, optional
        Extracts the string content from call_fn's return value.
        Defaults to str(response).

    Returns
    -------
    str
        The best narrative produced (highest score, or last attempt).
    """
    if extract_text is None:
        def extract_text(r: Any) -> str:  # type: ignore[misc]
            if hasattr(r, "content"):
                return str(r.content)
            return str(r)

    best_text: str = ""
    best_score: float = 0.0
    hint: str | None = None

    for attempt in range(max_retries + 1):
        try:
            raw = await call_fn(hint)
            text = extract_text(raw).strip()  # type: ignore[misc]
        except Exception as exc:
            logger.warning("reflect_and_retry [%s] attempt %d failed: %s", label, attempt + 1, exc)
            if attempt == max_retries:
                return best_text or ""
            continue

        try:
            result = evaluate_fn(text)
            score = result.overall_score
        except Exception as exc:
            logger.debug("reflect_and_retry [%s] evaluation error: %s", label, exc)
            score = 1.0  # if evaluation fails, accept the output
            result = None

        if score > best_score:
            best_score = score
            best_text = text

        logger.debug(
            "reflect_and_retry [%s] attempt=%d score=%.2f threshold=%.2f",
            label, attempt + 1, score, threshold,
        )

        if score >= threshold:
            if attempt > 0:
                logger.info(
                    "reflect_and_retry [%s] passed on attempt %d (score=%.2f)",
                    label, attempt + 1, score,
                )
            return text

        # Build improvement hint for next attempt
        if result and hasattr(result, "improvement_hints") and result.improvement_hints:
            hints_text = "; ".join(result.improvement_hints[:3])
            hint = (
                f"Önceki yanıt kalite kontrolünden geçemedi (puan: {score:.2f}/{threshold:.2f}). "
                f"Lütfen şunları iyileştirin: {hints_text}. "
                f"Daha özgün, sayısal veriye dayalı ve somut aksiyonlar içeren bir yanıt yazın."
            )
            logger.info(
                "reflect_and_retry [%s] retry %d — hints: %s",
                label, attempt + 1, hints_text,
            )
        else:
            hint = (
                f"Önceki yanıt yetersiz bulundu (puan: {score:.2f}). "
                "Daha spesifik, sayısal ve aksiyon odaklı bir yanıt yazın."
            )

    logger.warning(
        "reflect_and_retry [%s] exhausted %d retries — best score=%.2f (threshold=%.2f)",
        label, max_retries, best_score, threshold,
    )
    return best_text
