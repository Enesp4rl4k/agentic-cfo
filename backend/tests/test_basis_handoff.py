"""A basis tag is not dropped at a hand-off, and no text claims more than the basis says.

The runway block says whether its balance is `known` or `assumed`, its date, its months, the assumption sentence
and whether two statements may be one account. Everything built on its figures carries that and says no more:
"kanıtlı" appears only for a known basis, and only a proven basis may raise a critical alert.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.agents.orchestration.proactive_alerts import AlertEvent, ProactiveAlertOrchestrator
from app.agents.risk.gercek_kri import cfo_kri
from app.models.proactive_alert import ProactiveAlert
from app.services import cascade_inputs
from app.services.cascade_inputs import RunwayBasis, baseline_from
from app.services.decision_packet import build_situation
from tests.db_helpers import gecici_oturum

KNOWN_MSG = "12 Mart 2026 ekstresindeki bakiyeye göre kasa 200.000 ₺."
ASSUMED_MSG = (
    "12 Mart 2026 ekstresindeki bakiyeye göre kasa 200.000 ₺. "
    "Bakiye zayıf kanıta dayanıyor (yalnızca 2 bakiye adımıyla doğrulandı), varsayım olarak alındı."
)
IDENTITY_MSG = (
    "12 Mart 2026 ekstresindeki bakiyeye göre kasa 200.000 ₺. 2 ekstrenin aynı hesaba ait olduğu bilinmiyor."
)


def block(kind: str) -> dict[str, Any]:
    base: dict[str, Any] = {
        "status": "computed", "opening_cash_cents": 200_000_00, "as_of": "2026-03-12", "months_used": 3,
        "avg_monthly_net_cents": -50_000_00, "runway_months": 2.0, "assumptions": [],
        "basis": "known", "balance_basis": "known", "identity_uncertain": False, "identity_note": None,
        "message": KNOWN_MSG, "level": "critical",
    }
    if kind == "assumed":
        base.update(basis="assumed", balance_basis="assumed", message=ASSUMED_MSG)
    if kind == "identity":
        base.update(identity_uncertain=True, identity_note="2 ekstrenin aynı hesaba ait olduğu bilinmiyor", message=IDENTITY_MSG)
    return base


# ── the basis object ─────────────────────────────────────────────────────────────────────────────────────────────

def test_the_basis_keeps_every_field_and_only_known_is_proven():
    for kind, proven in (("known", True), ("assumed", False), ("identity", False)):
        _, basis = baseline_from(block(kind))
        d = basis.to_dict()
        assert d["proven"] is proven
        assert {"basis", "balance_basis", "as_of", "months_used", "assumptions", "identity_uncertain",
                "identity_note", "message", "cash_known"} <= set(d)
        assert ("kanıtlı" in basis.sentence()) is proven, (kind, basis.sentence())
    assert "yalnızca 2 bakiye adımıyla doğrulandı" in baseline_from(block("assumed"))[1].sentence()
    assert "aynı hesaba ait olduğu bilinmiyor" in baseline_from(block("identity"))[1].sentence()
    assert "kanıtlı" not in RunwayBasis("no_balance", None, None, None, 0).sentence()


# ── the scan end to end ──────────────────────────────────────────────────────────────────────────────────────────

class _Ctx:
    last_cfo_result = {
        "pnl": {"revenue": 12_000_000, "total_opex": 18_000_000},
        "cashflow": {"net_change": -5_000_000}, "forecast": {},
    }
    last_chro_result = last_cto_result = last_cmo_result = last_coo_result = None


@pytest_asyncio.fixture
async def db():
    import app.models  # noqa: F401

    async with gecici_oturum() as session:
        yield session


async def _scan(db, monkeypatch, runway_block: dict[str, Any]) -> list[ProactiveAlert]:
    async def ctx(org_id, session=None):
        return _Ctx()

    async def company_runway(session, org_id):
        return runway_block

    monkeypatch.setattr("app.services.company_context.get_company_context", ctx)
    monkeypatch.setattr(cascade_inputs, "company_runway", company_runway)
    orch = ProactiveAlertOrchestrator(db=db)

    async def kris(org_id: str) -> dict[str, Any]:
        return {"kris": [], "posture": {"red_kris": [], "upcoming_red": [], "cascade_ready": [
            {"name": "Nakit ömrü", "cascade_trigger": "cash_crisis", "cascade_params": {"runway_months": 0.0}}]}}

    monkeypatch.setattr(orch, "_compute_current_kris", kris)
    assert (await orch.scan_and_alert("org-1"))["alerts_created"] == 1
    return list((await db.execute(select(ProactiveAlert))).scalars())


async def test_measured_inputs_still_fire_a_critical_alert_that_says_proven(db, monkeypatch):
    (alert,) = await _scan(db, monkeypatch, block("known"))
    assert alert.severity == "critical"
    assert "kanıtlı kasa bakiyesi (2026-03-12)" in (alert.body or "")


async def test_assumed_inputs_fire_a_capped_labelled_alert_with_the_runways_own_sentence(db, monkeypatch):
    (alert,) = await _scan(db, monkeypatch, block("assumed"))
    assert alert.severity == "high"
    assert "kanıtlı" not in (alert.body or "")
    assert "yalnızca 2 bakiye adımıyla doğrulandı" in (alert.body or "")


async def test_an_open_account_identity_question_caps_the_alert_too(db, monkeypatch):
    (alert,) = await _scan(db, monkeypatch, block("identity"))
    assert alert.severity == "high" and "kanıtlı" not in (alert.body or "")
    assert "aynı hesaba ait olduğu bilinmiyor" in (alert.body or "")


# ── the KRI path ─────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("kind", ["known", "assumed", "identity"])
async def test_the_kri_alert_carries_the_forecasts_basis(kind, db):
    forecast = {"scenarios": {"base": {"runway_months": 2.0}}, "runway": block(kind)}
    (kri,) = [k for k in cfo_kri({}, forecast) if k["name"] == "Nakit Ömrü"]
    assert kri["basis"] == block(kind)["basis"]
    orch = ProactiveAlertOrchestrator(db=db)
    alert = await orch._create_kri_alert("org-1", kri, "critical")
    assert isinstance(alert, AlertEvent)
    if kind == "known":
        assert alert.severity == "critical" and "Dayanak sınırı" not in alert.body
    else:
        assert alert.severity == "high" and "Dayanak sınırı" in alert.body
        assert "kanıtlı" not in alert.body


# ── the other hand-offs ──────────────────────────────────────────────────────────────────────────────────────────

async def test_the_trigger_action_result_carries_the_basis(db, monkeypatch):
    from app.models.trigger import TriggerDefinitionRow  # noqa: F401
    from app.services.triggers import actions

    async def company_runway(session, org_id):
        return block("assumed")

    class Ctx(_Ctx):
        last_cfo_result: dict[str, Any] = {"pnl": {"revenue": 12_000_000, "total_opex": 18_000_000}}

    async def ctx(org_id, session=None):
        return Ctx()

    monkeypatch.setattr("app.services.company_context.get_company_context", ctx)
    monkeypatch.setattr(cascade_inputs, "company_runway", company_runway)

    class Definition:
        action_params = {"trigger": "cash_crisis", "runway_months": 0.5}

    result = await actions._cascade_simulate(db, "org-1", Definition(), {})  # type: ignore[arg-type]
    assert result["basis"]["basis"] == "assumed" and result["basis"]["proven"] is False
    assert "kanıtlı" not in str(result["basis"]["message"])


async def test_the_cascade_api_answer_carries_the_basis(monkeypatch):
    from tests.api_helpers import bellek_istemcisi, kullanici

    async def company_runway(session, org_id):
        return block("assumed")

    monkeypatch.setattr(cascade_inputs, "company_runway", company_runway)
    async with bellek_istemcisi() as client:
        headers, org_id, _ = await kullanici(client, "basis@example.com")
        r = await client.post("/api/v1/cascade/simulate", headers=headers, json={
            "trigger": "key_person_loss", "org_id": org_id, "key_person_loss": {"role": "cto"}})
        assert r.status_code == 200, r.text
        assert r.json()["baseline_basis"]["basis"] == "assumed"


async def test_the_decision_packet_situation_keeps_the_runway_basis(db):
    class Job:
        id = "j"
        min_confidence = None

    forecast = {"scenarios": {"base": {"runway_months": 2.0}}, "runway": block("assumed")}
    situation = await build_situation(db, Job(), {}, {}, forecast)  # type: ignore[arg-type]
    assert situation["runway_basis"] == "assumed"
    assert "yalnızca 2 bakiye adımıyla doğrulandı" in situation["runway_note"]
    known = await build_situation(db, Job(), {}, {}, {**forecast, "runway": block("known")})  # type: ignore[arg-type]
    assert known["runway_basis"] == "known" and known["runway_note"] is None


def test_no_alert_path_uses_the_role_coefficient_what_if():
    import app.agents.orchestration.proactive_alerts as alerts

    source = Path(alerts.__file__).read_text(encoding="utf-8")
    assert "multidomain_counterfactual" not in source and "analyze_headcount_change" not in source


def test_the_hire_what_if_labels_its_role_coefficient_as_an_assumption():
    from app.services.multidomain_counterfactual import MultidomainCounterfactual

    engine = MultidomainCounterfactual(
        pnl={"revenue": 12_000_000_00, "total_opex": 8_000_000_00},
        chro_data={"total_headcount": 20, "avg_monthly_salary_try": 60_000},
    )
    result = engine.analyze_headcount_change(delta=2, role_type="sales")
    assert "varsayım: bu rol için gelir etkisi %20" in str(result.to_dict())


# ── every consumer of the runway × {known, assumed, unknown} ─────────────────────────────────────────────────────

from app.agents.ceo import (
    board_deck_agent,
    okr_agent,
    strategic_priorities_agent,
    swot_agent,
    synthesis_agent,
)
from app.agents.nl_query_engine import execute_nl_query
from app.services import (
    context_builder,
    executive_report_pdf,
    llm_structured,
    unified_report,
)
from app.services.runway_display import PROMPT_RULE, runway_for_display

UNKNOWN_BLOCK = {
    "status": "no_balance", "basis": None, "message": "Kasa bakiyesi bilinmiyor — nakit pisti hesaplanamadı.",
    "opening_cash_cents": None, "runway_months": None,
}


def forecast_in(state: str) -> dict[str, Any]:
    scenario = {"label": "Baz", "twelve_month_net": 100_000, "months": []}
    if state == "unknown":
        return {"scenarios": {"base": {**scenario, "runway_months": None}}, "runway": UNKNOWN_BLOCK}
    return {"scenarios": {"base": {**scenario, "runway_months": 2.0}}, "runway": block(state)}


def consumer_outputs(state: str) -> dict[str, str]:
    forecast = forecast_in(state)
    fin = synthesis_agent._condense_financial_summary({"pnl": {}, "cashflow": {}, "forecast": forecast})
    tech = {"infra_waste_cents": 100, "infra_cost_cents": 1000}
    risks = synthesis_agent._detect_cross_risks(fin, tech)
    return {
        "one_page": board_deck_agent._build_one_page_summary(fin, {}, risks, [], "2026", "Co"),
        "cross_risks": str(risks),
        "priorities": str(strategic_priorities_agent._build_priorities_from_risks([], fin, {})),
        "swot": str(swot_agent._extract_swot(fin, {}, None, None, None, None, None)),
        "okr": str(okr_agent._infer_okrs(fin, {}, [], "2026")),
        "unified_cfo": str(unified_report._build_cfo_section({"pnl": {}, "forecast": forecast})),
        "nl_query": str(execute_nl_query("nakit runway ne kadar?", {"forecast": forecast}, [])),
        "executive_pdf_html": executive_report_pdf._build_html(
            {"pnl": {"currency": "TRY"}, "cashflow": {}, "forecast": forecast}, "Co", "2026", "now"),
        "context_builder": context_builder._summarise_forecast(forecast),
        "forecast_narrative": str(llm_structured._forecast_narrative_template(forecast)),
        "helper": runway_for_display(forecast).prompt_line(),
    }


@pytest.mark.parametrize("state", ["known", "assumed", "unknown"])
def test_every_consumer_says_only_what_the_basis_warrants(state):
    outputs = consumer_outputs(state)
    for name, text in outputs.items():
        low = text.replace(PROMPT_RULE, "").lower()  # the instruction to the model names the word on purpose
        if state != "known":
            assert "kanıtlı" not in low, (state, name)
        if state == "unknown":
            assert not re.search(r"(?<![\d.])2(\.0)? (ay|months)", low), (state, name)
        if state == "known" and name in ("one_page", "helper"):
            assert "ekstresine göre" in text, (state, name)
        if state == "assumed" and name in ("one_page", "helper"):
            assert "yalnızca 2 bakiye adımıyla doğrulandı" in text, (state, name)
        if state == "unknown" and name in ("one_page", "helper"):
            assert "bilinmiyor" in text, (state, name)
    if state != "known":
        # No severity word on the runway's own authority.
        for name in ("cross_risks", "priorities"):
            assert "'severity': 'critical'" not in outputs[name], (state, name)


def test_a_known_runway_may_still_raise_a_critical_risk():
    risks = synthesis_agent._detect_cross_risks(
        synthesis_agent._condense_financial_summary({"pnl": {}, "cashflow": {}, "forecast": forecast_in("known")}),
        {"infra_waste_cents": 100, "infra_cost_cents": 1000},
    )
    assert any(r["severity"] == "critical" for r in risks)


def test_the_unknown_runway_one_pager_does_not_print_zero_months():
    fin = synthesis_agent._condense_financial_summary({"pnl": {}, "cashflow": {}, "forecast": forecast_in("unknown")})
    page = board_deck_agent._build_one_page_summary(fin, {}, [], [], "2026", "Co")
    assert "Nakit Pisti:     bilinmiyor" in page and "0.0 ay" not in page


def test_llm_context_lines_carry_the_basis_and_the_do_not_restate_rule():
    from app.agents.chat_agent import (
        _build_executive_context,  # noqa: F401  (the prompt builders share the helper)
    )

    for state in ("assumed", "unknown"):
        line = runway_for_display(forecast_in(state)).prompt_line()
        assert PROMPT_RULE in line
    chat = context_builder._summarise_forecast(forecast_in("assumed"))
    assert "yalnızca 2 bakiye adımıyla doğrulandı" in chat
