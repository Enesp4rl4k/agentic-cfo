"""Process-wide async Redis client — one connection pool, shared by every
cross-process concern (rate limiter, SSE event bus, cache, locks).

Why this exists (DDIA Ch.1/Ch.3):
  - The rate limiter kept per-process dicts, so two uvicorn workers each
    enforced half the limit. The SSE bus kept per-process queues, so events
    published in the ARQ worker never reached the API process. Both need the
    *same* broker connection.
  - `cache_service` used to open and close a TCP connection on every cache
    op. One pool, reused.

Behaviour contract:
  - Disabled (returns None) when DISABLE_REDIS=true or USE_SQLITE=true —
    the dev/test parity gate `cache_service` already used. Tests therefore
    never touch a broker and every call site keeps its local fallback.
  - Reachability failures mark a short cooldown instead of stalling every
    request on a connect timeout: callers get None, fall back locally, and
    the next attempt happens after the cooldown.
  - Never raises. A broker outage degrades to the old single-process
    behaviour; it does not take the API down.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

_client: Any | None = None
_unavailable_until: float = 0.0
_COOLDOWN_SECONDS = 15.0


def redis_enabled() -> bool:
    """False in dev-without-broker and in tests (see module docstring)."""
    if os.environ.get("DISABLE_REDIS") == "true":
        return False
    return os.environ.get("USE_SQLITE") != "true"


def mark_unavailable(exc: BaseException | None = None) -> None:
    """A command failed — stop handing out the client for a short while."""
    global _unavailable_until
    _unavailable_until = time.monotonic() + _COOLDOWN_SECONDS
    logger.warning(
        "Redis unavailable (%s) — cross-process features degrade to "
        "single-process fallback for %ds",
        exc,
        _COOLDOWN_SECONDS,
    )


async def get_redis() -> Any | None:
    """Return the shared client, or None when disabled / in cooldown.

    `from_url` is lazy — connection errors surface on the first command, so
    callers must wrap the command in try/except and call `mark_unavailable`.
    """
    global _client
    if not redis_enabled():
        return None
    if time.monotonic() < _unavailable_until:
        return None
    if _client is None:
        try:
            import redis.asyncio as aioredis

            from app.config import get_settings

            settings = get_settings()
            if not settings.redis_url:
                return None
            _client = aioredis.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_connect_timeout=0.5,
                socket_timeout=0.5,
            )
        except Exception as exc:  # import / config failure — stay degraded
            mark_unavailable(exc)
            return None
    return _client


def reset_redis() -> None:
    """Drop the singleton (tests / shutdown). Does not close connections the
    caller may still be awaiting — use `aclose_redis` for a clean shutdown."""
    global _client, _unavailable_until
    _client = None
    _unavailable_until = 0.0


async def aclose_redis() -> None:
    """Close the shared pool (application shutdown)."""
    global _client
    if _client is None:
        return
    try:
        await _client.aclose()
    except Exception as exc:  # pragma: no cover - shutdown path
        logger.debug("Redis close failed: %s", exc)
    finally:
        _client = None
