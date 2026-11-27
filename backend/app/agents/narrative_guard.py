"""Bir açıklama yazılamadı diye hesaplanmış analiz kaybolmasın.

Agents compute their metrics from the data, then ask the LLM for a narrative
about them. Nine of those narrative functions let an LLM failure propagate,
and the agent's outer `except` then returned `ok=False` — discarding metrics
that were already computed, correct, and had nothing to do with the LLM. A
timeout, a rate limit or a missing key turned a cloud bill's real analysis into
an empty result.

`narrative_guard` keeps the analysis: on failure it logs and returns a note
that says the narrative is missing and the figures still stand.
`tests/test_narrative_guard.py` fails if a narrative function is added without
either this guard or its own fallback.
"""
from __future__ import annotations

import functools
import logging
from collections.abc import Awaitable, Callable
from typing import ParamSpec

logger = logging.getLogger(__name__)

ACIKLAMA_YOK = (
    "Açıklama üretilemedi (dil modeline ulaşılamadı). "
    "Rakamlar veriden hesaplandı ve geçerlidir."
)

P = ParamSpec("P")


def narrative_guard(fn: Callable[P, Awaitable[str]]) -> Callable[P, Awaitable[str]]:
    @functools.wraps(fn)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> str:
        try:
            return await fn(*args, **kwargs)
        except Exception as exc:
            logger.warning("%s: açıklama üretilemedi, rakamlar korunuyor: %s", fn.__name__, exc)
            return ACIKLAMA_YOK

    return wrapper


# ── "the AI step did not run": said on the template text itself ──────────────
# When the data mode is `off`, or masked mode refused the call (fail closed), the narrative functions answer
# from their template. The template then says so in the product's own words for that case (tr / en), so a
# person never mistakes it for an AI-written text. `model_gateway._open_egress` records the skip.
AI_STEP_SKIPPED = {
    "off": "Yapay zekâ adımı atlandı (LLM_DATA_MODE=off): şablon metin. / AI step skipped (data mode off): template text.",
    "refused": "Yapay zekâ adımı atlandı (maskeli modda veri gönderilmedi): şablon metin. / "
               "AI step skipped (nothing sent in masked mode): template text.",
}


def labels_skipped_ai_step(fn: Callable[P, Awaitable[str]]) -> Callable[P, Awaitable[str]]:
    """Prefix the template with the skipped-AI-step note when the gateway refused or `off` applied."""

    @functools.wraps(fn)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> str:
        from app.platform.llm_egress.session import skipped_steps

        token = skipped_steps.set([])
        try:
            text = await fn(*args, **kwargs)
            skipped = skipped_steps.get() or []
        finally:
            skipped_steps.reset(token)
        if skipped and isinstance(text, str):
            note = AI_STEP_SKIPPED["refused" if "refused" in skipped else "off"]
            return text if text.startswith(note) else f"{note}\n{text}"
        return text

    return wrapper
