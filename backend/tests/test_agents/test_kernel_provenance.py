"""Every C-level kernel result carries a `provenance` block (Faz 12 honesty pass).

The kernel API endpoints (`/cto-kernel/*`, `/chro-kernel/*`, ...) return these
dicts verbatim, so this is the API contract for the provenance badge.
"""
from __future__ import annotations

import pytest

from app.platform.provenance import provenance_block


class TestProvenanceBlock:
    def test_benchmark_is_synthetic(self):
        b = provenance_block("benchmark", 0.5)
        assert b["synthetic"] is True
        assert b["data_source"] == "benchmark"
        assert b["confidence"] == 0.5

    def test_real_is_not_synthetic(self):
        assert provenance_block("real", 0.9)["synthetic"] is False

    def test_none_defaults_to_benchmark(self):
        assert provenance_block(None)["data_source"] == "benchmark"
        assert provenance_block(None)["synthetic"] is True

    def test_rule_based_is_not_synthetic(self):
        # deterministic catalog evaluation, not a fabricated metric
        assert provenance_block("rule_based")["synthetic"] is False


@pytest.mark.asyncio
async def test_cto_kernel_attaches_synthetic_provenance_for_cfo_only_input():
    from app.agents.cto.cto_kernel import run_cto_kernel

    res = await run_cto_kernel(
        pnl={"revenue": 1_000_000_00, "net_income": 100_000_00, "operating_expenses": 400_000_00},
        cashflow={"operating": 50_000_00},
        forecast={},
    )
    assert "provenance" in res
    assert res["provenance"]["synthetic"] is True
    assert res["provenance"]["data_source"] in {"estimated", "benchmark"}
    # the raw kernel figure still carries its own label
    assert res["output"]["data_source"] == res["provenance"]["data_source"]


@pytest.mark.asyncio
async def test_chro_kernel_attaches_provenance():
    from app.agents.chro.chro_kernel import run_chro_kernel

    res = await run_chro_kernel(
        pnl={"revenue": 800_000_00, "operating_expenses": 300_000_00},
        cashflow={},
        forecast={},
    )
    assert res["provenance"]["synthetic"] is True


@pytest.mark.asyncio
async def test_risk_kernel_marks_derived_when_no_register():
    from app.agents.risk.risk_kernel import run_risk_kernel

    res = await run_risk_kernel(pnl={"revenue": 500_000_00}, cashflow={}, forecast={})
    assert res["provenance"]["data_source"] == "derived"
    assert res["provenance"]["synthetic"] is True
