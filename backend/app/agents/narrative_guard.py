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
