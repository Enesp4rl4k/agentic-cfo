"""Plan v10 §13.3 / E2 — no sector number is attributed to a source that did not give it.

`services/benchmark.py` kept sector medians in a hard-coded dictionary and labelled every
answer "TCMB/BDDK Sektör İstatistikleri 2023-2024". Nothing showed those numbers came
from a TCMB or BDDK table. They also reached the P&L narrative as "vs sector median", so
the model could write that a company sat below the sector as if a source said so, and the
CMO compared ROAS (divided by ten) with the gross margin of a default sector.

Until a verified, dated table exists, the values stay but are labelled for what they are,
and nothing a person or the model reads rests on them.
"""
from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

from app.services.benchmark import UNVERIFIED_SOURCE, VERIFIED, BenchmarkEngine

ROOT = Path(__file__).resolve().parents[2]

PNL = {
    "revenue": 1_000_000_00, "gross_margin": 0.30, "net_margin": 0.05, "ebitda_margin": 0.12,
    "total_opex": 200_000_00,
}


def test_the_values_are_marked_unverified_and_name_no_authority():
    answer = BenchmarkEngine().get_sector_benchmark("gross_margin", "manufacturing")
    assert VERIFIED is False
    assert answer["verified"] is False
    assert answer["source"] == UNVERIFIED_SOURCE
    assert "TCMB" not in answer["source"] and "BDDK" not in answer["source"]
    assert answer["last_updated"] is None


def test_a_full_comparison_says_it_is_unverified():
    report = BenchmarkEngine().build_full_comparison(PNL, sector="manufacturing")
    assert report["verified"] is False


def test_the_pnl_narrative_is_not_given_the_sector_comparison(monkeypatch):
    import asyncio

    from app.agents import pnl_agent

    seen: dict = {}

    async def fake_narrative(pnl, settings):
        seen.update(pnl)
        return SimpleNamespace(to_text=lambda: "metin")

    monkeypatch.setattr("app.services.llm_structured.get_pnl_narrative", fake_narrative)
    text = asyncio.run(pnl_agent._generate_cfo_narrative(dict(PNL), settings=None, sector="manufacturing"))

    assert text == "metin"
    assert "_benchmark_context" not in seen


def test_the_cmo_does_not_compare_roas_with_a_gross_margin():
    import asyncio

    from app.agents.cmo.campaign_agent import run_campaign_agent

    csv = "campaign,channel,spend,revenue,conversions,clicks,impressions\nYaz,meta,1000,4000,20,500,10000\n"
    out = asyncio.run(run_campaign_agent({"campaign_csv": csv}, {}))
    assert out["campaigns"] is not None
    assert "benchmark" not in out["campaigns"]


def test_no_screen_or_service_text_names_tcmb_bddk_as_the_source_of_those_values():
    """A ratchet: the false attribution must not come back in code or in what the UI says."""
    claim = re.compile(r"TCMB/BDDK Sekt[öo]r (İstatistikleri|Statistics)", re.IGNORECASE)
    hits = []
    for base in (ROOT / "backend" / "app", ROOT / "frontend" / "src"):
        for path in base.rglob("*"):
            if path.suffix not in {".py", ".ts", ".tsx"} or "node_modules" in path.parts:
                continue
            if claim.search(path.read_text(encoding="utf-8", errors="ignore")):
                hits.append(str(path.relative_to(ROOT)))
    assert hits == []
