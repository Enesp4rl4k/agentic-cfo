"""Plan v6 §S0 — unknown is never shown as calm, and scores are read the right way round.

Live run on 2026-10-24: Risk with no inputs reported "acceptable (0.0/10)";
COO with no measured component reported 0.0 — "ideal" on its higher-is-worse
scale; the CEO SWOT read the CTO's higher-is-worse score as higher-is-better
(a critical 8/10 became a strength); the board deck printed a made-up "5.0/10"
tech score and a "0.0 months" critical runway when either was unknown; and a
client could write any "agent result" into the company context.
"""
from __future__ import annotations

from typing import Any

import pytest

from app.agents.ceo.board_deck_agent import _build_one_page_summary, _build_slides
from app.agents.ceo.swot_agent import _extract_swot
from app.agents.coo.orchestrator import node_coo_summary
from app.agents.risk.orchestrator import node_risk_summary
from tests.api_helpers import bellek_istemcisi, kullanici


def _no_llm(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record narrative-model calls (and make them fail like a placeholder key)."""
    calls: list[str] = []

    async def fake(**kw: Any) -> str:
        calls.append(kw.get("prompt", ""))
        raise RuntimeError("no model in tests")

    monkeypatch.setattr("app.platform.model_gateway.complete_text", fake)
    return calls


# ── Risk ──────────────────────────────────────────────────────────────────────


async def test_risk_with_no_inputs_is_no_data_not_acceptable(monkeypatch):
    calls = _no_llm(monkeypatch)
    out = await node_risk_summary(
        {"register": {"total_risks": 0}, "losses": {"total_events": 0},
         "kris": {"total_kris": 0}, "logs": []},
        {},
    )
    s = out["risk_summary"]
    assert s["risk_posture"] == "no_data"
    assert s["enterprise_risk_score"] is None
    assert s["component_scores"] == {"register": None, "losses": None, "kri": None}
    assert "düşük risk" in s["narrative"]  # says plainly it is not a low-risk result
    assert calls == []  # nothing to assess → no model asked to invent


async def test_risk_weights_renormalise_over_what_was_measured(monkeypatch):
    _no_llm(monkeypatch)
    out = await node_risk_summary(
        {"register": {"total_risks": 4, "enterprise_risk_score": 8.0},
         "losses": {"total_events": 0}, "kris": {"total_kris": 0}, "logs": []},
        {},
    )
    s = out["risk_summary"]
    # Only the register was measured: its 8.0 is the score, not 8.0 × 0.35 = 2.8.
    assert s["enterprise_risk_score"] == 8.0
    assert s["risk_posture"] == "critical"
    assert s["component_scores"]["losses"] is None


# ── COO ───────────────────────────────────────────────────────────────────────


async def test_coo_with_nothing_measured_is_unknown(monkeypatch):
    calls = _no_llm(monkeypatch)
    out = await node_coo_summary({"logs": []}, {})
    s = out["coo_summary"]
    assert s["overall_ops_score"] is None
    assert s["operational_efficiency_score"] is None
    assert "ölçülmedi" in s["narrative"]
    assert calls == []


async def test_coo_names_a_missing_input_instead_of_showing_zero(monkeypatch):
    calls = _no_llm(monkeypatch)
    await node_coo_summary(
        {"logs": [], "processes": {"efficiency_score": 2.0},
         "sla": {"sla_breach_rate": 0.0, "avg_nps_score": 60}},
        {},
    )
    assert calls, "a measured run still asks the model"
    assert "Kaynak verisi: ölçülmedi" in calls[0]
    assert "Kaynak Kullanımı: %0" not in calls[0]


# ── CEO reads scores the right way round ──────────────────────────────────────


def _swot(tech: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    return _extract_swot({}, tech, None, None, None, None, None)


def test_swot_reads_the_cto_risk_scale_correctly():
    critical = _swot({"overall_health_score": 8.5})
    assert not any("teknoloji" in i["text"].lower() for i in critical["strengths"])
    assert any("Yuksek teknoloji riski" in i["text"] for i in critical["weaknesses"])

    healthy = _swot({"overall_health_score": 2.0})
    assert any("Dusuk teknoloji riski" in i["text"] for i in healthy["strengths"])
    assert not any("teknoloji" in i["text"].lower() for i in healthy["weaknesses"])


def test_swot_makes_no_tech_claim_without_a_cto_run():
    out = _swot({})
    for bucket in out.values():
        assert not any("teknoloji" in i["text"].lower() for i in bucket)


def test_board_deck_does_not_invent_a_tech_score_or_a_runway_alarm():
    slides = _build_slides({"revenue_cents": 100_000_00, "net_income_cents": 10_000_00,
                            "cash_runway_months": None}, {}, [], [], "2026-Q3")
    cards = {m["label"]: m for m in slides[0]["key_metrics"]}
    assert cards["Teknoloji Sağlığı"]["value"] == "—"
    assert cards["Teknoloji Sağlığı"]["label_detail"] == "Ölçülmedi"
    assert cards["Nakit Pisti"]["alert"] is None
    assert "0.0 ay" not in cards["Nakit Pisti"]["value"]
    assert "ölçülmedi" in slides[0]["narrative"]

    page = _build_one_page_summary({}, {}, [], [], "2026-Q3", "Örnek A.Ş.")
    text = page if isinstance(page, str) else str(page)
    assert "5.0/10" not in text


# ── No client writes into the company context ─────────────────────────────────


async def test_context_cannot_be_written_by_a_client():
    async with bellek_istemcisi() as client:
        headers, _, _ = await kullanici(client, "baglam@example.com")
        res = await client.post(
            "/api/v1/context/me", headers=headers,
            json={"agent": "risk", "result": {"risk_summary": {"risk_posture": "acceptable"}}},
        )
        assert res.status_code == 405
