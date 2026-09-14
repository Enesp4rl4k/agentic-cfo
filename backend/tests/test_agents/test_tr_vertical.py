"""Tests for the L3 TR accounting vertical."""
from __future__ import annotations

import pytest

from app.agents.state import AgentRunConfig
from app.agents.tr_vertical import TR_VERTICAL_DEPTH_LEVEL, run_tr_vertical
from app.platform.policies import MAX_AUTOPILOT_DEPTH, PLATFORM_DEPTH

_CFG = AgentRunConfig(require_review=False, auto_proceed_min_confidence=0.0)

GOOD = """\
date,description,amount,type,category
2024-01-05,Ofis Kirasi,-8000,expense,rent
2024-01-10,Musteri A,25000,income,sales
2024-01-15,Elektrik,-1500,expense,utilities
2024-01-20,Musteri B,18000,income,sales
2024-01-25,COGS,-4000,expense,cogs
2024-01-30,Danismanlik,12000,income,services
"""


@pytest.fixture
def _csv(tmp_path):
    def _w(text: str, name: str = "tr") -> str:
        f = tmp_path / f"{name}.csv"
        f.write_text(text, encoding="utf-8")
        return str(f)

    return _w


def test_depth_registry_marks_only_this_vertical_l3():
    assert TR_VERTICAL_DEPTH_LEVEL == MAX_AUTOPILOT_DEPTH
    assert PLATFORM_DEPTH["tr_accounting_vertical"] == 3
    assert all(v <= 2 for k, v in PLATFORM_DEPTH.items() if k != "tr_accounting_vertical")


async def test_vertical_runs_all_stages(_csv):
    res = await run_tr_vertical(
        job_id="trv-001",
        file_path=_csv(GOOD),
        file_type="csv",
        company_name="TechNova",
        period="2024-01",
        run_config=_CFG,
    )
    assert res.stage == "done"
    assert res.cfo.get("pnl") is not None
    assert res.accounting is not None
    assert res.accounting["islem_sayisi"] == 6
    assert res.board_deck_pdf_bytes and len(res.board_deck_pdf_bytes) > 50
    assert isinstance(res.approval_required, bool)


async def test_vertical_halts_cleanly_on_bad_file(_csv):
    res = await run_tr_vertical(
        job_id="trv-002",
        file_path=_csv("", "empty"),
        file_type="csv",
        run_config=_CFG,
    )
    assert res.stage == "cfo"
    assert res.errors
    assert res.accounting is None


async def test_vertical_never_auto_approves_when_accounting_flags_review(_csv, monkeypatch):
    async def _fake_muhasebe(**_kw):
        return {
            "islem_sayisi": 6,
            "kayit_sayisi": 6,
            "onay_bekleyen": 3,
            "dengeli": True,
            "hata": None,
        }

    monkeypatch.setattr(
        "app.agents.accounting.orchestrator.run_muhasebe_pipeline", _fake_muhasebe
    )
    res = await run_tr_vertical(
        job_id="trv-003",
        file_path=_csv(GOOD),
        file_type="csv",
        run_config=_CFG,
    )
    assert res.approval_required is True
    assert any("onay bekliyor" in r for r in res.approval_reasons)
    assert res.stage == "done"  # still completes the chain; just flags the gate
