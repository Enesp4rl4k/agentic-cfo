"""1.5 hydration UX — a stalled or missing Redis must not hang context reads.

Before this fix the connect path had only ``socket_connect_timeout`` (DNS
resolution and per-command reads were unbounded), so with Redis down a single
``get_company_context`` call could block 15–20s before the DB fallback. The
contract now: every Redis step costs ≤2s, and a failed connect enters a 30s
cooldown so the penalty is paid once per window, not on every request.
"""
from __future__ import annotations

import asyncio
import time

import pytest

from app.services import company_context as cc


class _HangingRedis:
    """A server that accepts the connection but never answers."""

    async def get(self, _key: str):
        await asyncio.sleep(6)
        return None

    async def setex(self, *_args: object, **_kwargs: object):
        await asyncio.sleep(6)


@pytest.mark.asyncio
async def test_hanging_redis_read_falls_back_within_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cc, "_redis_client", _HangingRedis())
    monkeypatch.setattr(cc, "_redis_retry_after", 0.0)

    start = time.monotonic()
    ctx = await cc.get_company_context("org-timeout-test")
    elapsed = time.monotonic() - start

    assert ctx.org_id == "org-timeout-test"
    assert elapsed < 4.0, f"context read hung {elapsed:.1f}s — Redis read bound missing"


@pytest.mark.asyncio
@pytest.mark.skipif(not cc._REDIS_AVAILABLE, reason="redis package not installed")
async def test_redis_init_ping_is_bounded_and_marks_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    class _SlowClient:
        async def ping(self) -> bool:
            await asyncio.sleep(6)
            return True  # pragma: no cover — cancelled first

    calls = {"n": 0}

    def _slow_from_url(*_args: object, **_kwargs: object):
        calls["n"] += 1
        return _SlowClient()

    monkeypatch.setattr(cc, "_redis_client", None)
    monkeypatch.setattr(cc, "_redis_retry_after", 0.0)
    monkeypatch.setattr(cc.aioredis, "from_url", _slow_from_url)

    start = time.monotonic()
    client = await cc._get_redis()
    elapsed = time.monotonic() - start

    assert client is None
    assert elapsed < 4.0, f"redis init hung {elapsed:.1f}s — ping bound missing"
    assert calls["n"] == 1

    # Cooldown: the next read must not pay the connect cost again.
    second = await cc._get_redis()
    assert second is None
    assert calls["n"] == 1, "failed connect must cool down instead of retrying per request"
