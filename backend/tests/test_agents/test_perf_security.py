"""
Unit and integration tests for Performance & Security upgrades:
  - OWASP Security Headers Middleware
  - Dual-tier CacheService (Redis + in-memory fallback)
  - Rate Limiting Middleware
  - GZip Compression and response headers
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.rate_limit import RateLimitMiddleware, _check_rate_limit
from app.middleware.security_headers import (
    DEFAULT_SECURITY_HEADERS,
    SecurityHeadersMiddleware,
)
from app.services.cache_service import (
    CacheService,
    get_cached_analytics,
    invalidate_org_analytics,
    llm_cached,
    set_cached_analytics,
)

# ── Test Security Headers ─────────────────────────────────────────────────────

def test_security_headers_injected():
    """Verify OWASP security headers are present on all responses."""
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/test-sec")
    async def sample_endpoint():
        return {"ok": True}

    client = TestClient(app)
    response = client.get("/test-sec")

    assert response.status_code == 200
    for header, value in DEFAULT_SECURITY_HEADERS.items():
        assert header in response.headers, f"Missing security header: {header}"
        assert response.headers[header] == value


def test_security_headers_custom_override():
    """Verify custom headers take precedence or augment default headers."""
    app = FastAPI()
    app.add_middleware(
        SecurityHeadersMiddleware,
        custom_headers={"X-Frame-Options": "SAMEORIGIN", "X-Custom-Sec": "enabled"}
    )

    @app.get("/test-custom-sec")
    async def sample():
        return {"data": "ok"}

    client = TestClient(app)
    res = client.get("/test-custom-sec")
    assert res.headers["X-Frame-Options"] == "SAMEORIGIN"
    assert res.headers["X-Custom-Sec"] == "enabled"
    assert res.headers["X-Content-Type-Options"] == "nosniff"


# ── Test Rate Limiting ────────────────────────────────────────────────────────

def test_rate_limit_sliding_window_unit():
    """Check sliding window algorithm directly."""
    key = "test_client_key_1"
    max_req = 3
    window = 10

    # 1st request
    allowed, remaining, retry = _check_rate_limit(key, max_req, window)
    assert allowed is True
    assert remaining == 2

    # 2nd request
    allowed, remaining, retry = _check_rate_limit(key, max_req, window)
    assert allowed is True
    assert remaining == 1

    # 3rd request
    allowed, remaining, retry = _check_rate_limit(key, max_req, window)
    assert allowed is True
    assert remaining == 0

    # 4th request (exceeded limit)
    allowed, remaining, retry = _check_rate_limit(key, max_req, window)
    assert allowed is False
    assert retry > 0


def test_rate_limit_middleware_headers():
    """Verify RateLimitMiddleware injects rate limit headers on allowed requests."""
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware)

    @app.get("/api/v1/test-rl")
    async def sample_api():
        return {"data": "ok"}

    client = TestClient(app)
    res = client.get("/api/v1/test-rl")
    assert res.status_code == 200
    assert "X-RateLimit-Limit" in res.headers
    assert "X-RateLimit-Remaining" in res.headers
    assert "X-RateLimit-Reset" in res.headers


# ── Test Cache Service ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cache_service_in_memory_get_set():
    """Verify in-memory fallback get, set, delete in CacheService."""
    cache = CacheService()

    # Get non-existent
    val = await cache.get("test:key:1")
    assert val is None

    # Set value
    data = {"metric": "ebitda", "value": 150000}
    await cache.set("test:key:1", data, ttl=60)

    # Get cached
    val = await cache.get("test:key:1")
    assert val == data

    # Delete
    await cache.delete("test:key:1")
    val_after = await cache.get("test:key:1")
    assert val_after is None


@pytest.mark.asyncio
async def test_cache_service_invalidate_pattern():
    """Verify pattern-based invalidation across namespaces."""
    cache = CacheService()

    await cache.set("cache:analytics:org_123:pnl", {"pnl": 100}, ttl=60)
    await cache.set("cache:analytics:org_123:cash", {"cash": 200}, ttl=60)
    await cache.set("cache:analytics:org_456:pnl", {"pnl": 300}, ttl=60)

    # Invalidate org_123 only
    deleted = await cache.invalidate_pattern("cache:analytics:org_123:*")
    assert deleted >= 2

    assert await cache.get("cache:analytics:org_123:pnl") is None
    assert await cache.get("cache:analytics:org_123:cash") is None
    assert await cache.get("cache:analytics:org_456:pnl") == {"pnl": 300}


@pytest.mark.asyncio
async def test_llm_cached_decorator():
    """Verify @llm_cached decorator caches results on identical arguments."""
    call_count = 0

    @llm_cached(ttl=60)
    async def mock_llm_analyzer(prompt: str, context_id: str) -> dict:
        nonlocal call_count
        call_count += 1
        return {"analysis": f"Processed {prompt} for {context_id}", "calls": call_count}

    res1 = await mock_llm_analyzer("Summarize Q3 P&L", "org-test")
    assert res1["calls"] == 1
    assert call_count == 1

    # Second call with identical arguments -> HIT cache
    res2 = await mock_llm_analyzer("Summarize Q3 P&L", "org-test")
    assert res2["calls"] == 1
    assert call_count == 1  # Not incremented

    # Different argument -> MISS cache
    res3 = await mock_llm_analyzer("Summarize Q4 P&L", "org-test")
    assert res3["calls"] == 2
    assert call_count == 2


@pytest.mark.asyncio
async def test_analytics_cache_helpers():
    """Verify get_cached_analytics, set_cached_analytics, and invalidate_org_analytics."""
    org_id = "org-test-789"
    endpoint = "/analytics/working-capital"
    params = {"period": "2026-Q2"}
    payload = {"working_capital": 45000000}

    # Set
    await set_cached_analytics(org_id, endpoint, params, payload, ttl=120)

    # Get
    cached = await get_cached_analytics(org_id, endpoint, params)
    assert cached == payload

    # Invalidate
    await invalidate_org_analytics(org_id)
    cleared = await get_cached_analytics(org_id, endpoint, params)
    assert cleared is None
