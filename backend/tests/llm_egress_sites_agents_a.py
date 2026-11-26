"""Canary drivers, part A: anomaly, audit, budget, CEO, chat, CHRO, CMO and compliance agents.

Each driver calls the REAL agent function with input whose text fields (titles, names, areas, categories, the
company name) carry the canary values, so what the fake provider records is what would have left the process.
"""
from __future__ import annotations

from tests.llm_egress_harness import CANARY, DESCRIPTION, Site, SiteEnv

QUESTION = (
    f"{CANARY.counterparty_short} firmasına ne kadar borcumuz var? Muhasebeci {CANARY.accountant} "
    f"{CANARY.iban_spaced} hesabına ödeme yapmamı önerdi, {CANARY.person} onayladı."
)
HISTORY = [
    {"role": "user", "content": f"{CANARY.company_short} için {CANARY.vendor_short} faturasını gördün mü?"},
    {"role": "assistant", "content": f"Evet, {CANARY.vendor} faturası {CANARY.email} adresinden geldi."},
]


async def _anomaly(env: SiteEnv) -> None:
    from app.agents.anomaly_agent import _generate_anomaly_narrative

    anomalies = [{
        "severity": "critical",
        "title": f"{CANARY.counterparty} tutarı olağandışı",
        "description": f"{env.description} tutarı ortalamanın çok üzerinde ({CANARY.vkn}).",
    }]
    await _generate_anomaly_narrative(anomalies, None)


async def _audit_summary(env: SiteEnv) -> None:
    from app.agents.audit.orchestrator import node_audit_summary

    raw = [
        {"area": CANARY.vendor_short, "category": "Kontrol", "severity": "critical"},
        {"area": CANARY.vendor_short, "category": "Kontrol", "severity": "high"},
        {"area": CANARY.counterparty_short, "category": "Kayıt", "severity": "low"},
    ]
    state = {
        "findings": {"finding_health_score": 40.0, "total_findings": 3, "open_critical": 1, "overdue_count": 1,
                     "repeat_findings": 2, "raw_findings": raw},
        "controls": {"overall_control_score": 55.0, "ineffective_controls": [{"id": 1}], "stale_controls": 1},
        "coverage": {"coverage_rate": 0.6, "high_risk_coverage": 0.5, "audit_backlog": 2, "total_units": 10},
        "logs": [],
    }
    await node_audit_summary(state, {})


async def _budget(env: SiteEnv) -> None:
    from app.agents.budget_agent import _generate_budget_narrative

    budget = {
        "items": [{"category": f"{CANARY.vendor} navlun", "budgeted": 100_000_00, "actual": 150_000_00,
                   "variance_pct": 50.0, "status": "over"},
                  {"category": CANARY.counterparty_short, "budgeted": 50_000_00, "actual": 40_000_00,
                   "variance_pct": -20.0, "status": "under"}],
        "total_budgeted": 150_000_00, "total_actual": 190_000_00, "total_variance_pct": 26.7,
        "over_budget_categories": ["x"],
    }
    await _generate_budget_narrative(budget, None)


async def _okr(env: SiteEnv) -> None:
    from app.agents.ceo.okr_agent import _generate_okr_narrative

    objectives = [{
        "title": f"{CANARY.company_short} için {CANARY.counterparty_short} sözleşmesini yenile",
        "overall_status": "at_risk", "momentum_label": "decelerating", "weight": 0.5,
        "key_results": [{"kr": f"{CANARY.person} ile {CANARY.vendor_short} toplantısı", "progress_pct": 40,
                         "status": "at_risk"}],
    }]
    await _generate_okr_narrative(objectives, "2026-Q1", 0.4, None)


async def _strategic_priorities(env: SiteEnv) -> None:
    from app.agents.ceo.state import CEORunConfig
    from app.agents.ceo.strategic_priorities_agent import run_strategic_priorities_agent

    risk = {
        "title": f"{CANARY.counterparty} bağımlılığı", "urgency": "now", "severity": "critical",
        "recommended_action": f"{CANARY.person} ile {CANARY.vendor} alternatifini görüş; IBAN {CANARY.iban_spaced}",
        "financial_impact_cents": 500_000_00, "domains": ["cfo"],
    }
    result = await run_strategic_priorities_agent(
        {"cross_risks": [risk], "financial_summary": {}, "tech_summary": {}, "job_id": "j1"}, CEORunConfig())
    assert result.ok, result.detail


def _dashboard(env: SiteEnv) -> dict:
    return {
        "pnl": {"revenue": 1_000_000, "gross_profit": 400_000, "gross_margin": 0.4, "ebitda": 100_000,
                "ebitda_margin": 0.1, "net_income": 50_000, "net_margin": 0.05, "currency": "TRY",
                "opex": {f"{CANARY.vendor_short}_navlun": 20_000.0}},
        "cashflow": {}, "forecast": {},
        "anomalies": [{"severity": "critical", "title": f"{CANARY.counterparty} ödemesi tekrar etti"}],
    }


def _transactions(env: SiteEnv) -> list[dict]:
    return [{"transaction_date": "2026-03-15", "type": "expense", "category": "other_expense",
             "amount_cents": 1_234_567_89, "currency": "TRY", "description": DESCRIPTION}]


async def _chat_cfo(env: SiteEnv) -> None:
    from app.agents.chat_agent import chat_with_cfo

    await chat_with_cfo(QUESTION, _dashboard(env), _transactions(env), conversation_history=HISTORY)


async def _stream_cfo(env: SiteEnv) -> None:
    from app.agents.chat_agent import stream_chat_with_cfo

    async for _ in stream_chat_with_cfo(QUESTION, _dashboard(env), _transactions(env),
                                        conversation_history=HISTORY):
        pass


def _ceo_kwargs(env: SiteEnv) -> dict:
    ceo = {
        "cross_risks": [{"severity": "high", "title": f"{CANARY.counterparty} bağımlılığı",
                         "recommended_action": f"{CANARY.person} ile görüş"}],
        "strategic_priorities": [{"rank": 1, "urgency": "now", "action": f"{CANARY.vendor} sözleşmesi",
                                  "owner": CANARY.accountant}],
        "financial_summary": {"revenue_cents": 100_000_00, "net_income_cents": 5_000_00, "net_margin": 0.05},
        "board_deck": {"one_page_summary": f"{CANARY.company} yönetim kurulu özeti, {CANARY.person}."},
    }
    cto = {"cto_summary": {"overall_health_score": 4.0, "narrative": f"{CANARY.company_short} altyapısı",
                           "top_risks": [{"severity": "high", "domain": "infra",
                                          "message": f"{CANARY.vendor} sunucusu"}]}}
    return {"ceo_result": ceo, "cto_result": cto, "dashboard": _dashboard(env),
            "transactions": _transactions(env), "conversation_history": HISTORY}


async def _chat_ceo(env: SiteEnv) -> None:
    from app.agents.chat_agent import chat_with_ceo

    await chat_with_ceo(QUESTION, **_ceo_kwargs(env))


async def _stream_ceo(env: SiteEnv) -> None:
    from app.agents.chat_agent import stream_chat_with_ceo

    async for _ in stream_chat_with_ceo(QUESTION, **_ceo_kwargs(env)):
        pass


async def _attrition(env: SiteEnv) -> None:
    from app.agents.chro.attrition_agent import _generate_attrition_narrative

    metrics = {"total_departures": 12, "avg_tenure_months": 18, "early_departure_rate": 0.3,
               "involuntary_departures_count": 2}
    survival = {"summary": {"annual_attrition_pct": 22, "survival_at_12m_pct": 70, "critical_risk_count": 3},
                "high_risk_cohorts": [{"department": f"{CANARY.vendor_short} lojistik",
                                       "level": f"{CANARY.person} ekibi"}]}
    await _generate_attrition_narrative(metrics, None, survival_result=survival)


async def _chro_summary(env: SiteEnv) -> None:
    from app.agents.chro.orchestrator import node_chro_summary

    state = {
        "headcount": {"total_headcount": 40, "avg_tenure_years": 2.5, "early_departure_rate": 0.2,
                      "alerts": [{"level": "critical",
                                  "message": f"{CANARY.person} ayrıldı; {CANARY.vendor_short} birimi sahipsiz"}]},
        "attrition": {"early_departure_rate": 0.2, "alerts": [
            {"level": "warning", "message": f"{CANARY.counterparty_short} bölümünde ayrılma arttı"}]},
        "compensation": {"total_employees": 40, "below_market_count": 5, "equity_penetration": 0.3,
                         "total_annual_comp": 10_000_000_00, "alerts": []},
        "logs": [],
    }
    await node_chro_summary(state, {})


async def _campaign(env: SiteEnv) -> None:
    from app.agents.cmo.campaign_agent import _generate_campaign_narrative

    metrics = {"overall_roas": 1.2, "total_spend_cents": 100_000_00, "total_revenue_cents": 120_000_00,
               "overall_cac_cents": 5_000_00, "underperforming": [{"campaign": CANARY.vendor_short}]}
    attribution = {"insight": f"{CANARY.counterparty_short} kanalı son dokunuşta {CANARY.person} kampanyasını geçti"}
    benchmark = {"metrics": {"roas": {"vs_median_pct": -15, "percentile_position": "alt çeyrek"}}}
    await _generate_campaign_narrative(metrics, None, attribution=attribution, benchmark=benchmark)


async def _cohort(env: SiteEnv) -> None:
    from app.agents.cmo.cohort_agent import _generate_cohort_narrative

    await _generate_cohort_narrative({"ltv_cac_ratio": 2.1, "churn_rate": 0.05, "avg_retention_30d": 0.6,
                                      "retention_trend": "stable", "cohorts_analyzed": 4}, None)


async def _funnel(env: SiteEnv) -> None:
    from app.agents.cmo.funnel_agent import _generate_funnel_narrative

    # bottleneck_stage is a stage name taken verbatim from the customer's funnel CSV
    await _generate_funnel_narrative({"overall_conversion_rate": 0.04, "avg_cycle_days": 21.0, "total_leads": 100,
                                      "won_count": 4, "bottleneck_stage": f"{CANARY.counterparty_short} teklif"},
                                     None)


async def _cmo_summary(env: SiteEnv) -> None:
    from app.agents.cmo.orchestrator import node_cmo_summary

    state = {
        "campaigns": {"overall_roas": 1.2, "underperforming": [], "alerts": [
            {"level": "critical", "message": f"{CANARY.vendor_short} kampanyası zarar ediyor"}]},
        "funnel": {"overall_conversion_rate": 0.04, "bottleneck_stage": f"{CANARY.counterparty_short} teklif",
                   "alerts": []},
        "cohorts": {"ltv_cac_ratio": 2.1, "churn_rate": 0.05, "retention_trend": "stable", "alerts": []},
        "logs": [],
    }
    await node_cmo_summary(state, {})


async def _compliance_summary(env: SiteEnv) -> None:
    from app.agents.compliance.orchestrator import node_compliance_summary

    state = {
        "company_name": CANARY.company,
        "policies": {"total_policies": 10, "active_policies": 8, "policies_needing_review": 2, "alerts": []},
        "violations": {"total_violations": 3, "overdue_violations": 1, "critical_open": 1, "remediation_rate": 40.0,
                       "open_violations": 2, "alerts": [], "recommendations": []},
        "regulations": {"compliance_coverage_pct": 60.0, "framework_scores": {}, "non_compliant_count": 2,
                        "frameworks": ["KVKK"], "alerts": [], "recommendations": []},
        "logs": [],
    }
    await node_compliance_summary(state, {})


_CHAT_OFF = ("chat endpoints answer 503 when the model is off: the site's contract is to raise LLMUnavailable "
             "(the router turns that into the 503), there is no template answer")

SITES: dict[str, Site] = {
    "agents/anomaly_agent.py::_generate_anomaly_narrative": Site(_anomaly),
    "agents/audit/orchestrator.py::node_audit_summary": Site(_audit_summary),
    "agents/budget_agent.py::_generate_budget_narrative": Site(_budget),
    "agents/ceo/okr_agent.py::_generate_okr_narrative": Site(_okr),
    "agents/ceo/strategic_priorities_agent.py::run_strategic_priorities_agent": Site(_strategic_priorities),
    "agents/chat_agent.py::chat_with_ceo": Site(_chat_ceo, off_raises=True, note=_CHAT_OFF),
    "agents/chat_agent.py::chat_with_cfo": Site(_chat_cfo, off_raises=True, note=_CHAT_OFF),
    "agents/chat_agent.py::stream_chat_with_ceo": Site(_stream_ceo, off_raises=True, note=_CHAT_OFF),
    "agents/chat_agent.py::stream_chat_with_cfo": Site(_stream_cfo, off_raises=True, note=_CHAT_OFF),
    "agents/chro/attrition_agent.py::_generate_attrition_narrative": Site(_attrition),
    "agents/chro/orchestrator.py::node_chro_summary": Site(_chro_summary),
    "agents/cmo/campaign_agent.py::_generate_campaign_narrative": Site(_campaign),
    "agents/cmo/cohort_agent.py::_generate_cohort_narrative": Site(
        _cohort, carries=False,
        note="the prompt formats only ltv_cac_ratio, churn_rate, avg_retention_30d and the retention_trend "
             "enum (improving/stable/degrading): numbers and an enum label, no tenant text"),
    "agents/cmo/funnel_agent.py::_generate_funnel_narrative": Site(_funnel),
    "agents/cmo/orchestrator.py::node_cmo_summary": Site(
        _cmo_summary, carries=False,
        note="the prompt formats overall_score, ROAS, conversion rate, LTV:CAC, churn and len(top_risks): "
             "numbers only; alert messages and the bottleneck stage name stay out of it"),
    "agents/compliance/orchestrator.py::node_compliance_summary": Site(_compliance_summary),
}
ALIASED: dict[str, str] = {}
