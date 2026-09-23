"""Cross-process features degrade to local behaviour when there is no
broker — returning None/False rather than raising, because every call
site keeps its single-process fallback (the old behaviour).

In tests USE_SQLITE=true pins `redis_enabled()` to False, which is
exactly the contract these fallbacks are written for: no broker in the
loop, no per-request connect latency, no test depending on an external
service.

Also pinned here: the cache's shared-client shape — operations must
never close the pool (rate limiter and SSE bus share it) and a broker
miss must still reach the memory tier.
"""
from __future__ import annotations

from app.api.analysis import _idempotency_seized
from app.core.redis_client import redis_enabled
from app.middleware.rate_limit import _check_rate_limit, _check_rate_limit_redis


def test_tests_run_without_a_broker():
    # The gate every fallback below relies on:
    assert redis_enabled() is False


async def test_rate_limit_returns_none_so_the_local_window_runs():
    verdict = await _check_rate_limit_redis("redis-key", 5, 60)
    assert verdict is None  # no broker → caller falls back to the deque

    # ...and the local window still answers with the same tuple shape:
    allowed, remaining, retry = _check_rate_limit("local-key", 5, 60)
    assert allowed is True
    assert remaining == 4  # limit 5, the current request counts itself
    assert retry == 0


async def test_idempotency_key_without_a_broker_does_not_block_dispatch():
    # No broker → no dedupe at the edge; the worker's atomic claim is the
    # guarantee that the work still runs exactly once (test_job_state).
    assert await _idempotency_seized("user-1", "retry-abc") is False


# ── Cache: shared pool, no per-op close, memory rescue ────────────────────────


class _SharedShapeRedis:
    """Fake with the shared client's command shape — and deliberately NO
    `aclose`: the old per-op close would AttributeError here, which is
    exactly the regression this pins."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self.store[key] = value

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)


async def test_cache_ops_never_close_the_shared_client(monkeypatch):
    from app.services import cache_service as cs

    fake = _SharedShapeRedis()

    async def _fake_get_redis():
        return fake

    monkeypatch.setattr(cs, "_get_redis", _fake_get_redis)
    cache = cs.CacheService()

    await cache.set("k", {"v": 1}, ttl=60)
    assert await cache.get("k") == {"v": 1}
    await cache.delete("k")
    assert await cache.get("k") is None


async def test_broker_eviction_rescues_from_the_memory_tier(monkeypatch):
    """`volatile-lru` may evict a TTL'd cache key under memory pressure.
    A broker miss must fall through to the in-memory twin, not return
    None and make every caller recompute."""
    from app.services import cache_service as cs

    fake = _SharedShapeRedis()

    async def _fake_get_redis():
        return fake

    monkeypatch.setattr(cs, "_get_redis", _fake_get_redis)
    cache = cs.CacheService()

    await cache.set("evicted", {"v": 2}, ttl=60)
    fake.store.clear()  # eviction happened on the broker side
    assert await cache.get("evicted") == {"v": 2}
