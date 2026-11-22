"""A missing input stays missing: no constant stands in for a company fact.

The reviewer's reproduction, verbatim: pnl + cashflow `net_change` -5,000,000 + forecast base runway None + no
HR data used to give runway 12, headcount 50, salary 30,000, cash 600,000 (never in the books), a 23/100 risk
naming "İnsan Kaynakları" from the invented headcount, and an alert sent by Slack, e-mail or in-app.
"""
from __future__ import annotations

from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.agents.orchestration.proactive_alerts import ProactiveAlertOrchestrator
from app.models.in_app_notification import InAppNotification
from app.models.outbox_message import OutboxMessage
from app.models.proactive_alert import ProactiveAlert
from app.services.cascade_simulator import CascadeInputsMissing, CascadeSimulator, TriggerType
from app.services.counterfactual_engine import (
    CounterfactualEngine,
    CounterfactualInputsMissing,
    compute_presets,
)
from app.services.decision_packet import build_preset_options
from tests.db_helpers import gecici_oturum

PNL = {"currency": "TRY", "revenue": 12_000_000_00, "total_opex": 8_000_000_00, "net_margin": 0.2,
       "opex": {"salary": 4_000_000_00, "rent": 1_000_000_00}}
REPRO = {
    "pnl": {"revenue": 12_000_000, "total_opex": 18_000_000},
    "cashflow": {"net_change": -5_000_000},
    "forecast": {"scenarios": {"base": {"runway_months": None}}},
}


def test_reviewers_reproduction_has_no_invented_inputs():
    sim = CascadeSimulator(**REPRO)
    assert sim.runway_months is None and sim.cash_balance is None
    assert sim.headcount is None and sim.avg_salary_try is None
    with pytest.raises(CascadeInputsMissing) as err:
        sim.simulate(TriggerType.CASH_CRISIS)
    assert any("nakit ömrü" in m for m in err.value.missing)


def test_revenue_drop_without_revenue_does_not_run_and_without_people_names_no_hr_effect():
    with pytest.raises(CascadeInputsMissing):
        CascadeSimulator(pnl={}, cashflow={}).simulate(TriggerType.REVENUE_DROP, drop_pct=0.3)
    result = CascadeSimulator(pnl={"revenue": 12_000_000, "total_opex": 9_000_000}).simulate(
        TriggerType.REVENUE_DROP, drop_pct=0.3)
    flat = str(result.to_dict())
    assert "new_runway_months" not in flat          # no cash: no runway after the drop
    assert "cac_increase_try" not in flat           # no CAC data


def test_scenario_assumptions_are_never_defaulted():
    sim = CascadeSimulator(pnl={"revenue": 12_000_000, "total_opex": 9_000_000})
    for trigger in (TriggerType.REVENUE_DROP, TriggerType.MARKET_SHOCK, TriggerType.KEY_PERSON_LOSS):
        with pytest.raises(CascadeInputsMissing) as err:
            sim.simulate(trigger)
        assert any("varsayım" in m for m in err.value.missing)


def test_cash_crisis_without_people_leaves_out_headcount_and_cost_not_the_rest():
    sim = CascadeSimulator(pnl={"revenue": 12_000_000, "total_opex": 18_000_000}, runway_months=3.0)
    result = sim.simulate(TriggerType.CASH_CRISIS)
    chro = next(i for i in result.domain_impacts if i.domain == "chro")
    assert "at_risk_headcount" not in chro.quantified_impact
    assert "replacement_cost_try" not in chro.quantified_impact
    assert "bilinmiyor" in chro.description


def test_cash_is_never_derived_from_net_change_times_runway():
    sim = CascadeSimulator(cashflow={"net_change": -300_000}, forecast={"scenarios": {"base": {"runway_months": 6}}})
    assert sim.cash_balance is None


# ── the hourly scan: nothing sent, a skip is recorded ───────────────────────────────────────────────────────────

class _Ctx:
    last_cfo_result = {"pnl": REPRO["pnl"], "cashflow": REPRO["cashflow"], "forecast": REPRO["forecast"]}
    last_chro_result = None
    last_cto_result = None
    last_cmo_result = None
    last_coo_result = None


@pytest_asyncio.fixture
async def db():
    import app.models  # noqa: F401

    async with gecici_oturum() as session:
        yield session


async def test_scan_with_missing_inputs_sends_nothing_and_records_the_skip(db, monkeypatch):
    async def ctx(org_id, session=None):
        return _Ctx()

    monkeypatch.setattr("app.services.company_context.get_company_context", ctx)
    orch = ProactiveAlertOrchestrator(db=db)

    async def kris(org_id: str) -> dict[str, Any]:
        return {"kris": [], "posture": {
            "red_kris": [], "upcoming_red": [],
            "cascade_ready": [{"name": "Nakit ömrü", "cascade_trigger": "cash_crisis",
                               "cascade_params": {}}],
        }}

    monkeypatch.setattr(orch, "_compute_current_kris", kris)
    result = await orch.scan_and_alert("org-1")

    assert result["alerts_created"] == 0
    assert (await db.execute(select(OutboxMessage))).scalars().all() == []
    assert (await db.execute(select(InAppNotification))).scalars().all() == []
    (skip,) = (await db.execute(select(ProactiveAlert))).scalars().all()
    assert skip.trigger == "scan_skipped" and skip.dispatched is False and skip.channels == "[]"
    assert "eksik girdi" in (skip.body or "")

    await orch.scan_and_alert("org-1")  # the hourly repeat does not pile up rows
    assert len((await db.execute(select(ProactiveAlert))).scalars().all()) == 1


# ── what-if presets and the decision packet ─────────────────────────────────────────────────────────────────────

def test_presets_never_use_a_stand_in_salary_or_churn():
    outcomes = {o.label: o for o in compute_presets(PNL, {"net_change": 1}, {})}
    hire, cut, price = outcomes["2 Kişi İşe Alma"], outcomes["Salary %20 Kesinti"], outcomes["%10 Fiyat Artışı"]
    assert hire.result is None and "maaş" in (hire.unavailable_reason or "")
    assert price.result is None and "varsayım" in (price.unavailable_reason or "")
    assert cut.result is not None and cut.result.base_net_impact > 0


def test_decision_packet_marks_unavailable_sections_with_the_reason():
    options = build_preset_options(PNL, {"net_change": 1}, {})
    by_id = {o["id"]: o for o in options}
    assert by_id["baseline"]["available"] is True
    assert by_id["preset_1"]["available"] is False and by_id["preset_1"]["base_net_impact"] is None
    assert by_id["preset_1"]["unavailable_reason"]
    assert by_id["preset_2"]["available"] is True and by_id["preset_2"]["base_net_impact"] is not None
    assert by_id["preset_3"]["available"] is False


def test_engine_refuses_inputs_it_does_not_have():
    engine = CounterfactualEngine(pnl={}, cashflow={})
    with pytest.raises(CounterfactualInputsMissing):
        engine.simulate_price_increase(increase_pct=0.1, churn_rate_increase=0.05)
    with pytest.raises(CounterfactualInputsMissing):
        CounterfactualEngine(pnl=PNL).simulate_cost_reduction(target_category="no-such-line", reduction_pct=0.2)


def test_unknown_runway_is_not_assumed_to_be_twelve():
    engine = CounterfactualEngine(pnl=PNL, cashflow={"net_change": -1}, forecast={})
    assert engine.runway_months is None
    result = engine.simulate_headcount_change(delta=2, avg_monthly_salary_try=50_000, productivity_gain_pct=0.1)
    assert result.cashflow_risk != "critical"


async def test_nl_question_without_assumptions_asks_for_them_and_never_fills_them():
    from app.services.nl_simulation_bridge import NLSimulationBridge

    bridge = NLSimulationBridge()
    for query, needle in (
        ("Fiyatı %10 artırırsak ne olur?", "müşteri kaybı"),
        ("Nakit biterse ne olur?", "kalan nakit ömrü"),
        ("Pazarlama bütçesini 50 bin tl artırırsak ne olur?", "ROAS"),
    ):
        result = await bridge.process(query, "org-1", context={"pnl": PNL})
        assert result.simulation_result is None, query
        assert needle in result.answer, (query, result.answer)
    # The salary and headcount are not in the data: the answer says so, with no figure.
    hc = await bridge.process("5 mühendis işe alırsam ne olur?", "org-1", context={"pnl": PNL})
    assert hc.simulation_result is None and "eksik" in hc.answer



async def test_skipped_scans_are_visible_to_owner_and_admin_only():
    from tests.api_helpers import bellek_istemcisi, kullanici

    async with bellek_istemcisi() as client:
        for email, role, sees in (("o@example.com", "owner", True), ("v@example.com", "viewer", False)):
            headers, org_id, _ = await kullanici(client, email, role=role)
            async with client._maker() as session:
                from app.services.scan_skips import record_skipped

                await record_skipped(session, str(org_id), "Nakit ömrü", ["nakit ömrü"])
            body = (await client.get("/api/v1/advanced/alert-history", headers=headers)).json()
            triggers = [a["trigger"] for a in body["data"]["alerts"]]
            assert ("scan_skipped" in triggers) is sees, (role, triggers)
