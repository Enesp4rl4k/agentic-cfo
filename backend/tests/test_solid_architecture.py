"""
SOLID & Clean Architecture Verification Tests.

Tests:
1. Single Responsibility Principle (SRP): Exporters, Dashboard builder, Financial primitives.
2. Open/Closed Principle (OCP): Dynamic custom IReportExporter and ITransactionParser.
3. Liskov Substitution Principle (LSP): ICacheProvider substitutability and In-Memory fallback.
4. Interface Segregation Principle (ISP): Granular protocols (ICacheReader, ICacheWriter, INarrativeGenerator).
5. Dependency Inversion Principle (DIP): ServiceContainer resolution and mock override.
6. DRY & KISS: Financial math primitives and unified resilient safe_llm_call.
"""
from __future__ import annotations

import os
import tempfile

import pytest

from app.core.container import ServiceContainer
from app.core.financial import (
    amount_to_cents,
    calc_growth_pct,
    calc_margin,
    calc_variance_pct,
    cents_to_amount,
    format_currency_try,
    format_currency_usd,
    safe_div,
)
from app.core.interfaces import (
    ICacheProvider,
    ICacheReader,
    ICacheWriter,
    IReportExporter,
)
from app.core.llm_client import safe_llm_call
from app.services.cache_service import CacheService
from app.services.exporters import DashboardExporter, ExcelReportExporter

# ── 1. Single Responsibility Principle (SRP) Tests ────────────────────────────

class TestSingleResponsibilityPrinciple:
    """Validate that components have a single, well-defined responsibility."""

    def test_excel_exporter_exports_valid_file(self):
        """ExcelReportExporter only handles Excel rendering."""
        exporter = ExcelReportExporter()
        pnl = {"revenue": 10000000, "cogs": 4000000, "gross_profit": 6000000, "net_income": 3000000}
        cashflow = {"operating": 2500000, "net_change": 2500000, "monthly_series": []}
        forecast = {"scenarios": {"base": {"label": "Base", "months": []}}}

        with tempfile.TemporaryDirectory() as tmp_dir:
            out_path = os.path.join(tmp_dir, "test_pnl.xlsx")
            res_path = exporter.export(pnl, cashflow, forecast, out_path)
            assert os.path.exists(res_path)
            assert os.path.getsize(res_path) > 0

    def test_dashboard_exporter_builds_valid_json(self):
        """DashboardExporter only handles JSON dashboard formatting."""
        pnl = {"revenue": 5000000, "net_income": 1000000, "gross_margin_pct": 50.0, "net_margin_pct": 20.0}
        cashflow = {"operating": 800000, "net_change": 800000}
        forecast = {"burn_rate_monthly": 100000, "runway_months": 12, "scenarios": {}}

        dashboard = DashboardExporter.build_dashboard_dict(pnl, cashflow, forecast, org_id="org-123")
        assert "summary" in dashboard
        assert dashboard["summary"]["revenue_cents"] == 5000000
        assert dashboard["meta"]["org_id"] == "org-123"


# ── 2. Open/Closed Principle (OCP) Tests ──────────────────────────────────────

class CustomCsvExporter(IReportExporter):
    """Extends reporting without modifying existing exporter classes."""
    format_name = "csv"

    def export(self, pnl: dict, cashflow: dict, forecast: dict, output_path: str, **kwargs) -> str:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(f"revenue,{pnl.get('revenue', 0)}\nnet_income,{pnl.get('net_income', 0)}\n")
        return output_path


class TestOpenClosedPrinciple:
    """Validate that the system can be extended without modifying source code."""

    def test_custom_report_exporter_implements_interface(self):
        exporter = CustomCsvExporter()
        assert isinstance(exporter, IReportExporter)

        with tempfile.TemporaryDirectory() as tmp_dir:
            out = os.path.join(tmp_dir, "report.csv")
            res = exporter.export({"revenue": 100, "net_income": 50}, {}, {}, out)
            assert os.path.exists(res)
            with open(res, encoding="utf-8") as f:
                content = f.read()
            assert "revenue,100" in content


# ── 3. Liskov Substitution Principle (LSP) Tests ──────────────────────────────

class TestLiskovSubstitutionPrinciple:
    """Validate that implementations can be substituted without breaking contracts."""

    @pytest.mark.asyncio
    async def test_cache_service_substitutes_icache_provider(self):
        cache = CacheService()
        assert isinstance(cache, ICacheProvider)
        assert isinstance(cache, ICacheReader)
        assert isinstance(cache, ICacheWriter)

        # Test contract operations in-memory without Redis
        key = "test:lsp:key"
        await cache.set(key, {"hello": "world"}, ttl=60)
        val = await cache.get(key)
        assert val == {"hello": "world"}

        count = await cache.invalidate_pattern("test:lsp:*")
        assert count >= 1
        assert await cache.get(key) is None

        stats = await cache.get_stats()
        assert stats["available"] is True


# ── 4. Interface Segregation Principle (ISP) Tests ───────────────────────────

class TestInterfaceSegregationPrinciple:
    """Validate that interfaces are cohesive and client-focused."""

    def test_protocol_checks(self):
        class ReadOnlyStorage:
            async def get(self, key: str):
                return None

        reader = ReadOnlyStorage()
        assert isinstance(reader, ICacheReader)
        assert not isinstance(reader, ICacheWriter)


# ── 5. Dependency Inversion Principle (DIP) Tests ─────────────────────────────

class TestDependencyInversionPrinciple:
    """Validate dependency injection container and mock overrides."""

    def test_service_container_resolution_and_override(self):
        test_container = ServiceContainer()

        class MockMemoryStore:
            def save_episode(self, episode):
                return "ep-mock-1"

            def get_recent_episodes(self, org_id, limit=5):
                return []

            def clear(self):
                pass

        test_container.register_singleton("IMemoryStore", MockMemoryStore())
        resolved = test_container.resolve("IMemoryStore")
        assert resolved.save_episode(None) == "ep-mock-1"


# ── 6. DRY & Financial Math Primitive Tests ───────────────────────────────────

class TestFinancialMathPrimitives:
    """Validate pure centralized financial formulas."""

    def test_safe_div(self):
        assert safe_div(10, 2) == 5.0
        assert safe_div(10, 0) == 0.0
        assert safe_div(10, 0, default=-1.0) == -1.0

    def test_cents_to_amount_and_reverse(self):
        assert cents_to_amount(10050) == 100.50
        assert cents_to_amount(0) == 0.0
        assert cents_to_amount(None) == 0.0

        assert amount_to_cents(100.50) == 10050
        assert amount_to_cents("150.75") == 15075
        assert amount_to_cents(None) == 0

    def test_calc_margin(self):
        assert calc_margin(2500, 10000) == 25.0
        assert calc_margin(0, 10000) == 0.0
        assert calc_margin(100, 0) == 0.0

    def test_calc_variance_pct(self):
        assert calc_variance_pct(120, 100) == 20.0
        assert calc_variance_pct(80, 100) == -20.0
        assert calc_variance_pct(50, 0) == 100.0

    def test_calc_growth_pct(self):
        assert calc_growth_pct(150, 100) == 50.0
        assert calc_growth_pct(100, 100) == 0.0

    def test_currency_formatting(self):
        assert format_currency_try(150000) == "₺1,500.00"
        assert format_currency_usd(150000) == "$1,500.00"


# ── 7. Unified Resilient LLM Client Tests ─────────────────────────────────────

class TestResilientLLMClient:
    """Validate safe_llm_call fallback handling."""

    @pytest.mark.asyncio
    async def test_safe_llm_call_returns_fallback_when_offline(self):
        res = await safe_llm_call(
            user_prompt="Say hello",
            fallback_text="Default summary commentary",
        )
        assert res == "Default summary commentary"
