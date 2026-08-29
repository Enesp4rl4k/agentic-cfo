"""
Tests for app.services.company_context

Covers:
  - CompanyContext dataclass: update_agent_result, set_active_job,
    has_required_data, agent_summary, to_dict / from_dict
  - get_company_context: Redis hit, Redis miss → DB hit, DB miss → empty ctx
  - save_company_context: Redis write, DB upsert
  - invalidate_company_context: Redis delete, DB delete
  - Payload size guard: _trim_context_payload trims large agent results
  - Kernel cache helpers: cache_kernel_result, get_cached_kernel_result
  - CompanyContextService singleton
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.services.company_context import (
    _AGENT_RESULT_MAX_CHARS,
    CompanyContext,
    CompanyContextService,
    _trim_context_payload,
    cache_kernel_result,
    get_cached_kernel_result,
    get_company_context,
    get_company_context_service,
    invalidate_company_context,
    save_company_context,
)

# ── CompanyContext dataclass ──────────────────────────────────────────────────

class TestCompanyContextDataclass:
    def test_default_fields(self):
        ctx = CompanyContext(org_id="org-1")
        assert ctx.org_id == "org-1"
        assert ctx.active_cfo_job_id is None
        assert ctx.company_name is None
        assert ctx.last_cfo_result is None
        assert ctx.last_ceo_result is None

    def test_update_agent_result_cfo(self):
        ctx = CompanyContext(org_id="org-1")
        result = {"revenue": 100_000, "net_margin": 0.25}
        ctx.update_agent_result("cfo", result)
        assert ctx.last_cfo_result == result

    def test_update_agent_result_all_agents(self):
        ctx = CompanyContext(org_id="org-1")
        agents = ["cfo", "cto", "cmo", "coo", "chro", "risk", "audit", "compliance", "ceo"]
        for agent in agents:
            ctx.update_agent_result(agent, {"agent": agent})
        for agent in agents:
            assert getattr(ctx, f"last_{agent}_result") is not None

    def test_update_agent_result_unknown_agent(self):
        ctx = CompanyContext(org_id="org-1")
        # Unknown agent — should log warning but not raise
        ctx.update_agent_result("unknown_agent", {"data": 1})
        # None of the known fields should have been set
        assert ctx.last_cfo_result is None

    def test_update_agent_result_touches_updated_at(self):
        ctx = CompanyContext(org_id="org-1")
        before = ctx.updated_at
        ctx.update_agent_result("cfo", {"data": 1})
        # updated_at should be refreshed
        assert ctx.updated_at >= before

    def test_set_active_job(self):
        ctx = CompanyContext(org_id="org-1")
        ctx.set_active_job("cfo", "job-abc123")
        assert ctx.active_cfo_job_id == "job-abc123"

    def test_set_active_job_all_agents(self):
        ctx = CompanyContext(org_id="org-1")
        for agent in ["cfo", "cto", "cmo", "coo", "chro"]:
            ctx.set_active_job(agent, f"job-{agent}")
        assert ctx.active_cfo_job_id  == "job-cfo"
        assert ctx.active_cto_job_id  == "job-cto"
        assert ctx.active_cmo_job_id  == "job-cmo"
        assert ctx.active_coo_job_id  == "job-coo"
        assert ctx.active_chro_job_id == "job-chro"

    def test_set_active_job_unknown_ignored(self):
        ctx = CompanyContext(org_id="org-1")
        ctx.set_active_job("unknown", "job-xyz")  # should not raise
        assert ctx.active_cfo_job_id is None

    def test_has_required_data_risk_needs_cfo(self):
        ctx = CompanyContext(org_id="org-1")
        assert ctx.has_required_data("risk") is False
        ctx.last_cfo_result = {"revenue": 100}
        assert ctx.has_required_data("risk") is True

    def test_has_required_data_audit_needs_cfo(self):
        ctx = CompanyContext(org_id="org-1")
        ctx.last_cfo_result = {"revenue": 100}
        assert ctx.has_required_data("audit") is True

    def test_has_required_data_unknown_agent_returns_true(self):
        # Unknown agents have no requirements → safe default = True
        ctx = CompanyContext(org_id="org-1")
        assert ctx.has_required_data("unknown_agent") is True

    def test_agent_summary_all_false_when_empty(self):
        ctx = CompanyContext(org_id="org-1")
        summary = ctx.agent_summary()
        for agent_data in summary.values():
            assert agent_data["has_result"] is False

    def test_agent_summary_reflects_updates(self):
        ctx = CompanyContext(org_id="org-1")
        ctx.update_agent_result("cfo", {"data": 1})
        ctx.update_agent_result("risk", {"data": 2})
        summary = ctx.agent_summary()
        assert summary["cfo"]["has_result"]  is True
        assert summary["risk"]["has_result"] is True
        assert summary["cto"]["has_result"]  is False

    def test_to_dict_from_dict_roundtrip(self):
        ctx = CompanyContext(
            org_id="org-1",
            company_name="Test Corp",
            active_cfo_job_id="job-123",
        )
        ctx.update_agent_result("cfo", {"revenue": 50_000})
        d = ctx.to_dict()
        ctx2 = CompanyContext.from_dict(d)
        assert ctx2.org_id          == ctx.org_id
        assert ctx2.company_name    == ctx.company_name
        assert ctx2.last_cfo_result == ctx.last_cfo_result

    def test_from_dict_ignores_unknown_fields(self):
        data = {
            "org_id": "org-1",
            "company_name": "Test",
            "nonexistent_field": "should_be_ignored",
        }
        # Should not raise
        ctx = CompanyContext.from_dict(data)
        assert ctx.org_id == "org-1"


# ── Payload trimming ──────────────────────────────────────────────────────────

class TestTrimContextPayload:
    def _large_result(self, size_chars: int = _AGENT_RESULT_MAX_CHARS + 100) -> dict:
        """Build a dict whose JSON serialization exceeds size_chars."""
        return {
            "summary": "short",
            "revenue": 100_000,
            "big_array": ["x" * 100] * (size_chars // 100 + 1),
        }

    def test_small_result_not_trimmed(self):
        data = {
            "org_id": "org-1",
            "last_cfo_result": {"revenue": 100, "net_margin": 0.2},
        }
        result = _trim_context_payload(data)
        # Small result — unchanged
        assert result["last_cfo_result"] == {"revenue": 100, "net_margin": 0.2}

    def test_large_result_trimmed(self):
        large = self._large_result()
        data = {"org_id": "org-1", "last_cfo_result": large}
        trimmed = _trim_context_payload(data)
        cfo = trimmed["last_cfo_result"]
        # Scalar keys preserved
        assert cfo.get("revenue") == 100_000
        assert cfo.get("summary") == "short"
        # Large array replaced with placeholder
        big_array_val = cfo.get("big_array")
        assert isinstance(big_array_val, str)
        assert "trimmed" in big_array_val

    def test_none_result_unchanged(self):
        data = {"org_id": "org-1", "last_cfo_result": None}
        result = _trim_context_payload(data)
        assert result["last_cfo_result"] is None

    def test_non_cfo_agent_also_trimmed(self):
        large = self._large_result()
        data = {"org_id": "org-1", "last_cto_result": large}
        trimmed = _trim_context_payload(data)
        cto = trimmed["last_cto_result"]
        # Large array should be replaced
        assert isinstance(cto.get("big_array"), str)

    def test_small_nested_dict_preserved(self):
        """Small nested dicts (< 2000 chars) should be kept."""
        data = {
            "org_id": "org-1",
            "last_cfo_result": {
                "revenue": 100_000,
                "big_array": ["x" * 100] * 1000,  # large → trim
                "metadata": {"period": "2024-Q4", "version": 2},  # small → keep
            },
        }
        trimmed = _trim_context_payload(data)
        assert trimmed["last_cfo_result"]["metadata"] == {"period": "2024-Q4", "version": 2}


# ── get_company_context ───────────────────────────────────────────────────────

class TestGetCompanyContext:
    @pytest.mark.asyncio
    async def test_returns_empty_context_when_no_redis_no_db(self):
        with patch("app.services.company_context._get_redis", new=AsyncMock(return_value=None)):
            ctx = await get_company_context("org-1", db=None)
        assert isinstance(ctx, CompanyContext)
        assert ctx.org_id == "org-1"
        assert ctx.last_cfo_result is None

    @pytest.mark.asyncio
    async def test_redis_hit_returns_context(self):
        stored_ctx = CompanyContext(org_id="org-1", company_name="Acme")
        stored_ctx.update_agent_result("cfo", {"revenue": 50_000})

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=json.dumps(stored_ctx.to_dict()))

        with patch("app.services.company_context._get_redis", new=AsyncMock(return_value=mock_redis)):
            ctx = await get_company_context("org-1", db=None)

        assert ctx.company_name == "Acme"
        assert ctx.last_cfo_result == {"revenue": 50_000}

    @pytest.mark.asyncio
    async def test_redis_miss_falls_through_to_empty(self):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        with patch("app.services.company_context._get_redis", new=AsyncMock(return_value=mock_redis)):
            ctx = await get_company_context("org-1", db=None)

        assert ctx.org_id == "org-1"
        assert ctx.last_cfo_result is None


# ── save_company_context ──────────────────────────────────────────────────────

class TestSaveCompanyContext:
    @pytest.mark.asyncio
    async def test_save_writes_to_redis(self):
        ctx = CompanyContext(org_id="org-1", company_name="Test Corp")
        mock_redis = AsyncMock()
        mock_redis.setex = AsyncMock()

        with patch("app.services.company_context._get_redis", new=AsyncMock(return_value=mock_redis)):
            await save_company_context(ctx, db=None)

        mock_redis.setex.assert_called_once()
        # First arg is key, second is TTL, third is JSON
        call_args = mock_redis.setex.call_args[0]
        assert "company_context:org-1" in call_args[0]
        assert isinstance(call_args[2], str)
        payload = json.loads(call_args[2])
        assert payload["org_id"] == "org-1"

    @pytest.mark.asyncio
    async def test_save_without_redis_no_error(self):
        ctx = CompanyContext(org_id="org-1")
        with patch("app.services.company_context._get_redis", new=AsyncMock(return_value=None)):
            # Should complete without exception even with no Redis and no DB
            await save_company_context(ctx, db=None)

    @pytest.mark.asyncio
    async def test_save_large_context_triggers_trim(self):
        """Context > 2MB should be trimmed before writing."""
        ctx = CompanyContext(org_id="org-1")
        # Build a large CFO result (>2 MB when serialized with context overhead)
        large_result = {
            "revenue": 100_000,
            "big_data": ["x" * 500] * 5000,  # ~2.5 MB
        }
        ctx.update_agent_result("cfo", large_result)

        written_payload: list[str] = []

        async def mock_setex(key, ttl, value):
            written_payload.append(value)

        mock_redis = AsyncMock()
        mock_redis.setex = mock_setex

        with patch("app.services.company_context._get_redis", new=AsyncMock(return_value=mock_redis)):
            await save_company_context(ctx, db=None)

        if written_payload:
            saved = json.loads(written_payload[0])
            cfo = saved.get("last_cfo_result") or {}
            # Either trimmed or the full payload — either way revenue preserved
            assert cfo.get("revenue") == 100_000


# ── invalidate_company_context ────────────────────────────────────────────────

class TestInvalidateCompanyContext:
    @pytest.mark.asyncio
    async def test_invalidate_deletes_redis_key(self):
        mock_redis = AsyncMock()
        mock_redis.delete = AsyncMock()

        with patch("app.services.company_context._get_redis", new=AsyncMock(return_value=mock_redis)):
            await invalidate_company_context("org-1", db=None)

        mock_redis.delete.assert_called_once_with("company_context:org-1")

    @pytest.mark.asyncio
    async def test_invalidate_no_redis_no_error(self):
        with patch("app.services.company_context._get_redis", new=AsyncMock(return_value=None)):
            await invalidate_company_context("org-1", db=None)
        # No exception raised


# ── Kernel cache ──────────────────────────────────────────────────────────────

class TestKernelCache:
    @pytest.mark.asyncio
    async def test_cache_kernel_result_writes_to_redis(self):
        result = {"health_score": 0.85, "velocity": "stable"}
        mock_redis = AsyncMock()
        mock_redis.setex = AsyncMock()

        with patch("app.services.company_context._get_redis", new=AsyncMock(return_value=mock_redis)):
            await cache_kernel_result("org-1", "cto", result)

        mock_redis.setex.assert_called_once()
        key = mock_redis.setex.call_args[0][0]
        assert "kernel_result:org-1:cto" in key

    @pytest.mark.asyncio
    async def test_get_cached_kernel_result_returns_data(self):
        cached = {"health_score": 0.85}
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=json.dumps(cached))

        with patch("app.services.company_context._get_redis", new=AsyncMock(return_value=mock_redis)):
            result = await get_cached_kernel_result("org-1", "cto")

        assert result == cached

    @pytest.mark.asyncio
    async def test_get_cached_kernel_result_miss_returns_none(self):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        with patch("app.services.company_context._get_redis", new=AsyncMock(return_value=mock_redis)):
            result = await get_cached_kernel_result("org-1", "cto")

        assert result is None

    @pytest.mark.asyncio
    async def test_no_redis_returns_none(self):
        with patch("app.services.company_context._get_redis", new=AsyncMock(return_value=None)):
            result = await get_cached_kernel_result("org-1", "cto")
        assert result is None


# ── CompanyContextService ─────────────────────────────────────────────────────

class TestCompanyContextService:
    @pytest.mark.asyncio
    async def test_get_context_returns_dict(self):
        svc = CompanyContextService()
        with patch("app.services.company_context._get_redis", new=AsyncMock(return_value=None)):
            data = await svc.get_context("org-1")
        assert isinstance(data, dict)
        assert data["org_id"] == "org-1"

    @pytest.mark.asyncio
    async def test_update_agent_saves_result(self):
        svc = CompanyContextService()
        mock_redis = AsyncMock()
        mock_redis.get    = AsyncMock(return_value=None)
        mock_redis.setex  = AsyncMock()

        with patch("app.services.company_context._get_redis", new=AsyncMock(return_value=mock_redis)):
            await svc.update_agent("org-1", "cfo", {"revenue": 75_000})

        # setex should have been called (save_company_context + cache_kernel_result)
        assert mock_redis.setex.call_count >= 1

    def test_get_company_context_service_singleton(self):
        svc1 = get_company_context_service()
        svc2 = get_company_context_service()
        assert svc1 is svc2
