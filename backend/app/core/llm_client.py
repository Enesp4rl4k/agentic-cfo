"""
Unified LLM Client Service — thin, resilient wrapper over the Model Gateway.

``safe_llm_call`` is kept for callers that want a never-raises helper with a
deterministic fallback string. It delegates to
``app.platform.model_gateway.complete_text`` so routing, retry, timeout, cost
logging and tracing still apply; it just swallows every failure and returns
``fallback_text`` instead.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def safe_llm_call(
    messages: list[Any] | None = None,
    system_prompt: str | None = None,
    user_prompt: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 600,
    fallback_text: str = "",
    model: str | None = None,
) -> str:
    """
    Execute a chat completion via the gateway with automatic fallback.

    When ``messages`` is given (a pre-built LangChain message list), its
    System/Human contents are flattened into ``system_prompt`` / ``user_prompt``.
    Any failure (no key, timeout, provider error) returns ``fallback_text``.
    """
    if messages:
        for m in messages:
            content = getattr(m, "content", None)
            role = type(m).__name__.lower()
            if content is None:
                continue
            if "system" in role and not system_prompt:
                system_prompt = content
            elif not user_prompt:
                user_prompt = content

    try:
        from app.platform.model_gateway import complete_text

        text = await complete_text(
            task="short_narrative",
            system_prompt=system_prompt,
            prompt=user_prompt or "",
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return text.strip() if text and text.strip() else fallback_text
    except Exception as exc:
        logger.debug("safe_llm_call failed (%s), returning fallback.", exc)
        return fallback_text
