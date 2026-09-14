"""Synthetic (kernel-extrapolated) results must not drive downstream automation.

Covers the Faz 12 "honesty pass" wiring in
`app.agents.orchestration.auto_chain`:

  - `_result_is_synthetic` classification
  - `on_agent_complete` holds CEO synthesis when the completing agent's result
    is synthetic, and still runs it when the result is real.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.agents.orchestration.auto_chain import _result_is_synthetic, on_agent_complete
from app.services.company_context import CompanyContext


def _ctx_with_cfo(org_id: str = "org-test") -> CompanyContext:
    ctx = CompanyContext(org_id=org_id)
    ctx.last_cfo_result = {
        "pnl": {"net_margin": 0.2, "revenue": 500_000},
        "forecast": {"scenarios": {"base": {"runway_months": 12.0}}},
        "anomalies": [],
        "alerts": [],
    }
    return ctx


class TestResultIsSynthetic:
    def test_provenance_synthetic_true(self):
        assert _result_is_synthetic({"provenance": {"synthetic": True}}) is True

    def test_provenance_synthetic_false(self):
        assert _result_is_synthetic({"provenance": {"synthetic": False}}) is False

    def test_falls_back_to_output_data_source(self):
        assert _result_is_synthetic({"output": {"data_source": "benchmark"}}) is True
        assert _result_is_synthetic({"output": {"data_source": "estimated"}}) is True
        assert _result_is_synthetic({"output": {"data_source": "real"}}) is False

    def test_risk_posture_shape(self):
        assert _result_is_synthetic({"posture": {"data_source": "derived"}}) is True

    def test_no_signal_is_not_synthetic(self):
        assert _result_is_synthetic({"pnl": {"revenue": 1}}) is False
        assert _result_is_synthetic({}) is False


@pytest.mark.asyncio
async def test_synthetic_cto_result_does_not_trigger_ceo_synthesis():
    ctx = _ctx_with_cfo()
    ceo_calls: list[str] = []

    async def _mock_ceo(*args, **kwargs):
        ceo_calls.append("ceo")

    with (
        patch("app.agents.orchestration.auto_chain.get_company_context", new=AsyncMock(return_value=ctx)),
        patch("app.agents.orchestration.auto_chain.save_company_context", new=AsyncMock()),
        patch("app.agents.orchestration.auto_chain._run_chained_agent", new=AsyncMock()),
        patch("app.agents.orchestration.auto_chain._run_ceo_synthesis", new=_mock_ceo),
    ):
        await on_agent_complete(
            "cto", "org-test",
            {"ok": True, "output": {"data_source": "benchmark"},
             "provenance": {"synthetic": True, "data_source": "benchmark"}},
            db=None,
        )

    assert ceo_calls == []


@pytest.mark.asyncio
async def test_real_cto_result_still_triggers_ceo_synthesis():
    ctx = _ctx_with_cfo()
    ceo_calls: list[str] = []

    async def _mock_ceo(*args, **kwargs):
        ceo_calls.append("ceo")

    with (
        patch("app.agents.orchestration.auto_chain.get_company_context", new=AsyncMock(return_value=ctx)),
        patch("app.agents.orchestration.auto_chain.save_company_context", new=AsyncMock()),
        patch("app.agents.orchestration.auto_chain._run_chained_agent", new=AsyncMock()),
        patch("app.agents.orchestration.auto_chain._run_ceo_synthesis", new=_mock_ceo),
    ):
        await on_agent_complete(
            "cto", "org-test",
            {"ok": True, "output": {"data_source": "real"},
             "provenance": {"synthetic": False, "data_source": "real"}},
            db=None,
        )

    assert ceo_calls == ["ceo"]
