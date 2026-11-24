"""Every consumer of a runway reports the SERVICE's class (PR #151 review, item 2).

The oracle below is written independently of `services/runway.py` (a plain restatement of the rule the owner reads:
known and current may be critical up to 3 months, anything up to 6 is a warning, up to 12 is only "izlemede"; an assumed
runway is capped at warning). Each consumer is called for the same company and reports back critical | warning |
watch | None; a consumer that by design shows a narrower slice (only the class, or only 3 months and under) is
compared with that slice of the oracle, said in its `MASK`.
"""
from __future__ import annotations

from typing import Any

import pytest

from app.agents.alert_agent import _check_cashflow
from app.agents.ceo.board_deck_agent import _runway_alert
from app.agents.ceo.strategic_priorities_agent import _build_priorities_from_risks
from app.agents.ceo.swot_agent import _extract_swot
from app.agents.ceo.synthesis_agent import _detect_cross_risks
from app.agents.cto.orchestrator import cfo_runway_line
from app.agents.forecast_agent import _build_forecast_alerts
from app.agents.orchestration.auto_chain import _cfo_has_cash_crisis
from app.agents.orchestration.cross_domain_hub import CrossDomainHub
from app.agents.risk.gercek_kri import cfo_kri
from app.api.ceo import _compute_overall_health
from app.services.agent_negotiation import CHRONegotiationResponder
from app.services.cascade_simulator import CascadeSimulator
from app.services.counterfactual_engine import CounterfactualEngine
from app.services.executive_report_pdf import _scenario_runway
from app.services.llm_structured import _forecast_narrative_template
from app.services.macro_stress import _risk_level
from app.services.negotiation.consensus_engine import _extract_claims
from app.services.prescriptive_recommender import PrescriptiveRecommender
from app.services.runway import runway_alert, runway_line
from app.services.runway_display import PROMPT_RULE, runway_for_display, view_from_fin
from app.services.semantic.brief import build_from_snapshot
from app.services.semantic.conflicts import detect_metric_conflicts
from app.services.semantic.types import CompanySemanticSnapshot, MetricPoint, Period
from tests.test_runway_single_source import BURN, _case, _forecast

# months -> (balance in cents). 5.000 a month of burn.
MONTHS = [1.5, 2.5, 3.0, 3.5, 5.0, 8.0, 10.0, 14.0]


def oracle(months: float, proven: bool) -> str | None:
    shown = round(months, 1)
    if shown <= 3:
        return "critical" if proven else "warning"
    if shown <= 6:
        return "warning"
    return "watch" if shown <= 12 else None


def cls_only(c: str | None) -> str | None:
    return c if c in ("critical", "warning") else None


def _build(months: float | None, proven: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    block = _case(None if months is None else int(months * BURN), 3 if proven else 25)
    return block, _forecast(block)


CASES = [(m, p) for m in MONTHS for p in (True, False)]
IDS = [f"{m:g}-{'known' if p else 'assumed'}" for m, p in CASES]


def _fin(forecast: dict[str, Any]) -> dict[str, Any]:
    view = runway_for_display(forecast)
    return {"cash_runway_months": view.months, "net_margin": 0.1, "monthly_burn_cents": BURN, **view.fin_fields()}


def _word(severity: str | None) -> str | None:
    return {"critical": "critical", "high": "warning", "warning": "warning"}.get(severity or "")


def _snapshot(months: float | None) -> CompanySemanticSnapshot:
    pts = [MetricPoint("finance.runway_months", months, "months")] if months is not None else []
    return CompanySemanticSnapshot(org_id="o", period=Period(key="2026-03"), currency="TRY", locale="tr-TR", metrics=pts)


@pytest.mark.parametrize(("months", "proven"), CASES, ids=IDS)
def test_every_consumer_reports_the_services_class(months: float, proven: bool) -> None:
    block, forecast = _build(months, proven)
    expect = oracle(months, proven)
    expect_class = cls_only(expect)
    attention = months <= 3
    fin = _fin(forecast)
    got: dict[str, Any] = {}

    # the service itself and its readers
    got["block"] = block["level"] or ("watch" if block["watch"] else None)
    view = runway_for_display(forecast)
    got["view"] = view.level or ("watch" if view.watch else None)
    got["briefing line"] = {"KRİTİK": "critical", "Uyarı": "warning", "DİKKAT": "warning"}.get(
        runway_line(block).split(":")[0], "watch" if "izlemede" in runway_line(block) else None)
    alert = runway_alert(block)
    got["runway alert"] = alert["level"] if alert and alert["level"] != "info" else None
    got["alert agent"] = _word(next(iter(a["severity"] for a in _check_cashflow({"operating": 0}, forecast)), None))
    kri = next(k for k in cfo_kri(None, forecast) if k["name"] == "Nakit Ömrü")
    got["KRI"] = {"red": "critical", "amber": "warning"}.get(kri["status"])
    scen = {"pessimistic": {"runway_months": None}, "base": {"twelve_month_net": -1}}
    got["forecast alert"] = next(iter(a["level"] for a in _build_forecast_alerts(scen, block) if a["basis"] == "runway"), None)
    text = _scenario_runway(forecast, "base")
    got["PDF text"] = "watch" if "izlemede" in text or view.watch else expect_class  # PDF carries the basis text
    got["board deck"] = _word(_runway_alert(view))

    # CEO agents, fed the financial summary
    risks = _detect_cross_risks(fin, {"infra_waste_cents": 100_000, "infra_cost_cents": 1})
    infra = [r for r in risks if r["risk_id"] == "cross-infra-cash-runway"]
    got["CEO cross-risk"] = _word(infra[0]["severity"]) if infra else None
    prios = _build_priorities_from_risks([], fin, {})
    emergency = next((p for p in prios if p["title"] == "Emergency cash conservation plan"), None)
    got["CEO priorities"] = _word(emergency["severity"]) if emergency else None
    swot = _extract_swot(fin, {}, None, None, None, None, None)
    threats = [t for t in swot["threats"] if "nakit" in str(t).lower() and "omru" in str(t).lower()]
    got["CEO swot"] = ("critical" if "Kritik" in str(threats) else "warning") if threats else None
    health = _compute_overall_health({"financial_summary": fin})
    base_health = _compute_overall_health({"financial_summary": {**fin, "cash_runway_months": None, "runway_basis": "unknown",
                                                                 "runway_level": None, "runway_proven": False}})
    delta = round((health or 0) - (base_health or 0), 1)
    got["health score"] = None if not proven else {-30.0: "critical", -10.0: "warning"}.get(delta, "watch" if delta == 0 and view.watch else None)

    # hub / auto chain / consensus / what-if engines
    hub = CrossDomainHub(forecast=forecast)
    ins = [i for i in hub._insights({"ayrilma_orani": 0.3}) if i.id == "talent_cash_cascade"]
    got["hub"] = _word(ins[0].severity) if ins else None

    class Ctx:
        last_cfo_result = {"forecast": forecast}

    got["auto chain"] = "warning" if _cfo_has_cash_crisis(Ctx) else None
    label = _extract_claims("cash_risk", Ctx)["cfo"].label
    got["consensus"] = {"kritik": "critical", "yüksek": "warning", "orta": "watch"}.get(label)
    engine = CounterfactualEngine(pnl={"revenue": 1_000_000, "total_opex": 900_000}, cashflow={"net_change": -12_000_00}, forecast=forecast)
    got["counterfactual"] = engine.runway_view.level or ("watch" if engine.runway_view.watch else None)
    got["macro stress"] = {"CRITICAL": "critical", "HIGH": "warning", "MODERATE": "watch"}.get(
        _risk_level(months, proven=proven))
    resp = CHRONegotiationResponder.__new__(CHRONegotiationResponder)
    plan = resp.build_hiring_plan_response(
        {"open_critical_roles": 10, "avg_monthly_salary_try": 50_000, "annual_turnover_rate": 0.1}, months, runway_proven=proven)
    got["hiring plan"] = {0: "critical", 3: "warning"}.get(plan.get("planned_hires"))
    sim = CascadeSimulator(pnl={"total_opex": 12_000_00}, forecast=forecast)
    impacts = sim._simulate_cash_crisis(months)
    got["cascade"] = "warning" if impacts[0].impact_score > 0 else None
    rec = PrescriptiveRecommender.analyze_and_prescribe(int(months * BURN), BURN, 1_000_000, 1_000_000)
    pay = next(a for a in rec.actions if a.category == "payables")
    got["prescriptive"] = "warning" if pay.priority == "high" else None
    narrative = _forecast_narrative_template({**forecast, "scenarios": {**forecast["scenarios"],
                                                                        "pessimistic": {"runway_months": None, "twelve_month_net": 0}}})
    base_risk = [r for r in narrative.risks if r.risk.startswith(("KRİTİK", "DİKKAT", "Uyarı", "Nakit pisti"))]
    got["LLM fallback narrative"] = (
        _word(base_risk[0].severity) if base_risk and base_risk[0].severity != "medium" else ("watch" if base_risk else None))

    # snapshot-fed consumers receive a runway only when it is KNOWN (an assumed one is withheld, by design)
    handed = months if proven else None
    brief = build_from_snapshot(_snapshot(handed))
    fin_f = [f for f in brief.findings if f.metric_ids == ["finance.runway_months"]]
    got["decision brief"] = _word(fin_f[0].severity) if fin_f else None
    conflicts = detect_metric_conflicts([MetricPoint("growth.overall_roas", 4.0, "ratio"),
                                         *([MetricPoint("finance.runway_months", handed, "months")] if handed is not None else [])])
    got["metric conflicts"] = "warning" if any(c["topic"] == "growth_vs_cash" for c in conflicts) else None
    got["CTO line"] = (
        "critical" if "KRİTİK" in cfo_runway_line({"runway_months": handed}) else
        "warning" if "Uyarı" in cfo_runway_line({"runway_months": handed}) else
        "watch" if "izlemede" in cfo_runway_line({"runway_months": handed}) else None) if handed is not None else None

    # What each consumer is meant to show of the oracle: all of it, only the class, or only a yes/no for "a class".
    def same(e): return e
    def cls(e): return cls_only(e)
    want: dict[str, Any] = {
        "block": same, "view": same, "briefing line": same, "PDF text": same, "consensus": same, "counterfactual": same,
        "macro stress": same, "LLM fallback narrative": same,
        "runway alert": cls, "alert agent": cls, "KRI": cls, "forecast alert": cls, "board deck": cls, "CEO cross-risk": cls,
        "hub": cls, "CEO swot": cls, "hiring plan": cls,
        "CEO priorities": lambda e: cls_only(e) if attention else None,       # only 3 months and under is a priority
        "health score": lambda e: e if proven else None,                       # scored on a proven runway only
        "decision brief": lambda e: cls_only(e) if proven else None,           # snapshot carries a KNOWN runway only
        "CTO line": lambda e: e if proven else None,
    }
    binary = {  # these only say "a class is on" or not
        "auto chain": lambda e: bool(cls_only(e)), "cascade": lambda e: bool(cls_only(e)),
        "prescriptive": lambda e: bool(cls_only(e)), "metric conflicts": lambda e: bool(cls_only(e)) and proven,
    }
    problems = [f"{n}: got {v!r}, wants {want[n](expect)!r}" for n, v in got.items() if n in want and v != want[n](expect)]
    problems += [f"{n}: got {got[n]!r}, wants {f(expect)!r}" for n, f in binary.items() if bool(got[n]) != f(expect)]
    missing = set(got) - set(want) - set(binary)
    assert not missing, f"no expectation for {missing}"
    assert not problems, f"{months} months, {'known' if proven else 'assumed'}, oracle {expect!r}: " + "; ".join(problems)


def test_unknown_balance_no_consumer_reports_a_class_or_a_figure() -> None:
    _, forecast = _build(None, True)
    view = runway_for_display(forecast)
    assert view.level is None and not view.watch and view.class_name == "unknown"
    assert _check_cashflow({"operating": 0}, forecast) == []
    assert [k for k in cfo_kri(None, forecast) if k["name"] == "Nakit Ömrü"] == []
    assert not _cfo_has_cash_crisis(type("C", (), {"last_cfo_result": {"forecast": forecast}}))
    assert "bilinmiyor" in _scenario_runway(forecast, "base")


# ── the watch band, the LLM-facing class, and the fallback narrative (PR #151 review, items 4, 5 and the blocker) ──

def test_the_watch_band_is_neutral_never_an_alert() -> None:
    from app.services.runway import watch_phrase

    block, forecast = _build(8.0, True)
    assert block["watch"] and block["level"] is None and not block["attention"]
    assert runway_alert(block) is None                                      # nothing sent
    line = runway_line(block)
    assert "izlemede" in line and not line.startswith(("KRİTİK", "DİKKAT", "Uyarı"))
    assert watch_phrase(8.0) == "Nakit pisti 8,0 ay — izlemede" and watch_phrase(8.0, en=True) == "Cash runway 8.0 months — on watch"
    assert _check_cashflow({"operating": 0}, forecast) == []
    assert not [i for i in CrossDomainHub(forecast=forecast)._insights({"ayrilma_orani": 0.3}) if i.id == "talent_cash_cascade"]
    for edge, watch in ((6.0, False), (6.04, False), (6.06, True), (12.0, True), (12.04, True), (12.06, False)):
        from app.services.runway import is_watch
        assert is_watch(edge) is watch, edge


def test_the_class_itself_reaches_the_models_input() -> None:
    for months, proven, word in ((1.5, True, "critical"), (1.5, False, "warning"), (8.0, True, "watch"), (14.0, True, "none")):
        _, forecast = _build(months, proven)
        view = runway_for_display(forecast)
        assert view.class_name == word and f"sınıfı (hizmetin kararı, değiştirme): {word}" in view.prompt_line()
        assert view_from_fin(_fin(forecast)).class_name == word               # the CEO agents' summary carries it too
    _, unknown = _build(None, True)
    assert runway_for_display(unknown).class_name == "unknown"
    assert "çelişen bir sınıf söyleme" in PROMPT_RULE


def test_the_fallback_narrative_carries_the_measured_class_and_cash_gone() -> None:
    def risks(months: float | None, proven: bool, cents: int | None = None) -> list[Any]:
        block = _case(cents if cents is not None else (None if months is None else int(months * BURN)), 3 if proven else 25)
        fc = _forecast(block)
        fc["scenarios"]["pessimistic"] = {"runway_months": None, "twelve_month_net": 0}
        return _forecast_narrative_template(fc).risks

    known = risks(1.5, True)
    assert [r.severity for r in known] == ["critical"] and known[0].risk.startswith("KRİTİK")
    assumed = risks(1.5, False)
    assert [r.severity for r in assumed] == ["high"] and assumed[0].risk.startswith("DİKKAT")
    assert "kritik" not in assumed[0].risk.lower() and "kanıtlı" not in assumed[0].risk.lower()
    gone = risks(None, True, -1_000_00)
    assert "nakit bitmiş" in gone[0].risk and "0.0 ay" not in gone[0].risk and gone[0].severity == "critical"
    gone_assumed = risks(None, False, -1_000_00)
    assert "son ekstreye göre nakit bitmiş görünüyor" in gone_assumed[0].risk.lower().replace("i̇", "i")
    watch = risks(8.0, True)
    assert [r.severity for r in watch] == ["medium"] and "izlemede" in watch[0].risk
    assert risks(None, True) == [] and risks(14.0, True) == []               # unknown: no figure, no risk
