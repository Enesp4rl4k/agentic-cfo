"""Canary drivers for the COO / CTO / risk / tax / multi-period / NL-query / ingestion narrative agents.

Each driver calls the REAL product function with canary-bearing input. Sites whose prompt is built only from
numbers, ratios and enum labels say so in `note` (carries=False) instead of pretending to carry tenant text.
"""
from __future__ import annotations

import json
import re

from tests.llm_egress_harness import CANARY, Site, SiteEnv

_ALERT = "{vendor} faturası ve {person} onayı için {iban} hesabı incelendi; tel {phone}"


def _alert_text(env: SiteEnv) -> str:
    c = env.canary
    return _ALERT.format(vendor=c.vendor, person=c.person, iban=c.iban_spaced, phone=c.phone) + f" {c.email}"


# ── COO ──────────────────────────────────────────────────────────────────────

async def _coo_summary(env: SiteEnv) -> None:
    from app.agents.coo.orchestrator import node_coo_summary

    state = {
        "processes": {"efficiency_score": 6.0, "alerts": [{"level": "critical", "message": _alert_text(env)}],
                      "bottleneck_process": env.canary.counterparty},
        "resources": {"avg_utilization_rate": 0.9},
        "sla": {"sla_breach_rate": 0.1, "avg_nps_score": 40.0},
        "logs": [],
    }
    await node_coo_summary(state, {})  # type: ignore[arg-type]


async def _process_narrative(env: SiteEnv) -> None:
    from app.agents.coo.process_agent import _generate_process_narrative
    from app.config import get_settings

    metrics = {"avg_cycle_time_days": 12.0, "efficiency_score": 6.5, "overloaded_processes": ["a"],
               "bottleneck_process": f"{env.canary.counterparty} onayı", "bottleneck_constraint_label": env.canary.person,
               "bottleneck_recommendation": _alert_text(env), "total_processes": 3}
    await _generate_process_narrative(metrics, get_settings())


async def _resource_narrative(env: SiteEnv) -> None:
    from app.agents.coo.resource_agent import _generate_resource_narrative
    from app.config import get_settings

    metrics = {"avg_utilization_rate": 0.82, "total_headcount": 14,
               "overutilized_teams": [{"team": env.canary.person}], "underutilized_teams": [{"team": env.canary.vendor}]}
    await _generate_resource_narrative(metrics, get_settings())


async def _sla_narrative(env: SiteEnv) -> None:
    from app.agents.coo.sla_agent import _generate_sla_narrative
    from app.config import get_settings

    metrics = {"sla_breach_rate": 0.12, "avg_response_time_hours": 5.5, "avg_nps_score": 41.0, "trend": "degrading",
               "total_tickets": 120, "high_risk_count": 4, "open_tickets": 9,
               "customer": env.canary.counterparty}  # unused key: proves the function ignores free text
    await _generate_sla_narrative(metrics, get_settings())


# ── CTO ──────────────────────────────────────────────────────────────────────

async def _incident_narrative(env: SiteEnv) -> None:
    from app.agents.cto.incident_agent import _generate_incident_narrative
    from app.config import get_settings

    metrics = {"total_incidents": 21, "by_severity": {"critical": 2, "high": 5, "medium": 9, "low": 5},
               "mttr_hours": 3.5, "mttd_hours": 0.8, "sla_breach_count": 4, "sla_breach_pct": 19.0, "trend": "degrading",
               "recurring_services": [{"service": f"{env.canary.vendor} ağ geçidi", "count": 6, "pct": 28.6}]}
    alerts = [{"level": "critical", "message": _alert_text(env)}]
    await _generate_incident_narrative(metrics, alerts, get_settings())


async def _infra_narrative(env: SiteEnv) -> None:
    from app.agents.cto.infra_agent import _generate_infra_narrative
    from app.config import get_settings

    metrics = {"total_cost_cents": 12_345_600, "mom_change_pct": 14.2, "waste_estimate_cents": 1_200_000,
               "top_cost_drivers": [{"service": f"{env.canary.vendor} depolama", "cost_cents": 5_000_000, "pct": 40.5}]}
    alerts = [{"level": "warning", "message": _alert_text(env)}]
    await _generate_infra_narrative(metrics, alerts, get_settings())


async def _cto_summary(env: SiteEnv) -> None:
    from app.agents.cto.orchestrator import node_cto_summary

    state = {
        "infra": {"mom_change_pct": 12.0, "waste_estimate_cents": 100_000, "total_cost_cents": 1_000_000,
                  "alerts": [{"level": "critical", "message": _alert_text(env)}]},
        "tech_debt": {"debt_score": 7.5, "hotspot_files": ["a.py"], "refactor_priorities": [{"area": "x"}]},
        "incidents": {"mttr_hours": 4.0, "sla_breach_pct": 10.0, "alerts": [], "trend": "stable"},
        "velocity": {"predictability_score": 0.6, "velocity_trend": "down", "alerts": []},
        "logs": [],
    }
    await node_cto_summary(state, {})  # type: ignore[arg-type]


async def _debt_narrative(env: SiteEnv) -> None:
    from app.agents.cto.tech_debt_agent import _generate_debt_narrative
    from app.config import get_settings

    metrics = {"debt_score": 6.8, "total_commits": 410, "active_contributors": 7, "churn_rate": 0.31,
               "bus_factor_files_count": 3,
               "hotspot_files": [{"file": f"src/{env.canary.vendor_short}/{env.canary.person}.py", "changes": 40,
                                  "authors": 2}]}
    await _generate_debt_narrative(metrics, get_settings())


async def _velocity_narrative(env: SiteEnv) -> None:
    from app.agents.cto.velocity_agent import _generate_velocity_narrative
    from app.config import get_settings

    metrics = {"sprints_analyzed": 6, "avg_velocity": 31.5, "velocity_trend": "down", "predictability_score": 0.62,
               "carryover_ratio": 0.2}
    alerts = [{"level": "warning", "message": _alert_text(env)}]
    await _generate_velocity_narrative(metrics, alerts, get_settings())


# ── Ingestion, multi-period, tax, risk, NL query ─────────────────────────────

def _ingestion_reply(texts: list[str]) -> str:
    """A model that echoes the vendor it was shown: a placeholder in masked mode, the real name in raw."""
    joined = "\n".join(texts)
    hit = re.search(r"\[[A-Z_]+_[0-9a-z]+\]", joined)
    vendor = hit.group(0) if hit else CANARY.counterparty
    return json.dumps([{"date": "15.03.2026", "amount": 1500.0, "type": "expense", "description": f"FAST {vendor}",
                        "vendor": vendor, "confidence": 0.9}], ensure_ascii=False)


async def _extract_transactions(env: SiteEnv) -> None:
    from app.agents.data_ingestion import _extract_transactions_with_llm
    from app.config import get_settings

    raw = (f"HESAP EKSTRESİ {env.canary.company}\n15.03.2026 {env.description} 1.500,00 TL\n"
           f"Alıcı: {env.canary.vendor} VKN {env.canary.vkn} TCKN {env.canary.tckn}")
    rows = await _extract_transactions_with_llm(raw, get_settings())
    assert isinstance(rows, list)


async def _multiperiod_narrative(env: SiteEnv) -> None:
    from app.agents.multi_period_agent import _generate_multiperiod_narrative
    from app.config import get_settings

    multi = {"mom": {"revenue_change_pct": 5.2, "net_change_pct": -3.1}, "yoy": {"revenue_yoy_pct": 18.0,
             "net_yoy_pct": 7.5}, "kpi_trends": {"revenue_trend": "up", "expense_trend": "up", "net_trend": "down"},
             "company_name": env.canary.company}  # unused key: the prompt never formats it
    await _generate_multiperiod_narrative(multi, get_settings())


async def _tax_narrative(env: SiteEnv) -> None:
    from app.agents.tax_agent import _generate_tax_narrative
    from app.config import get_settings

    tax = {"vat": {"net_vat_payable": 12_000_000}, "withholding": {"income_tax_withholding": 500_000,
           "ssi_employer": 700_000}, "corporate": {"corporate_tax_estimate": 3_000_000},
           "payment_calendar": [{"type": "KDV", "amount": 12_000_000, "due_date": "2026-04-26"}],
           "company_name": env.canary.company}  # unused key: the prompt never formats it
    await _generate_tax_narrative(tax, get_settings())


async def _risk_summary(env: SiteEnv) -> None:
    from app.agents.risk.orchestrator import node_risk_summary

    c = env.canary
    state = {
        "register": {"total_risks": 5, "enterprise_risk_score": 6.0, "mitigation_coverage": 0.5,
                     "unmitigated_critical": [{"title": f"{c.counterparty} tedarik riski {c.person}", "band": "critical"}],
                     "by_band": {"critical": 1}},
        "losses": {"total_events": 1, "total_net_loss": 250_000_00, "open_events": 1,
                   "top_loss_events": [{"description": f"{c.vendor} kaybı", "root_cause": "x"}]},
        "kris": {"total_kris": 2, "composite_kri_score": 4.0, "breached_red": [{"name": c.company, "value": 9,
                 "threshold_red": 5}], "breached_amber": []},
        "logs": [],
    }
    await node_risk_summary(state, {})  # type: ignore[arg-type]


def _nl_args(env: SiteEnv) -> tuple[str, dict, dict]:
    c = env.canary
    query = f"{c.counterparty} ({c.iban_spaced}) ile ilgili {c.person} ödemeleri toplamı nedir? {c.email}"
    result = {"intent": "vendor_total", "value": f"{c.vendor}: 1.234.567 TL, tel {c.phone}", "context": {}}
    dashboard = {"pnl": {"revenue": 5_000_000.0, "net_income": 800_000.0, "net_margin": 0.16},
                 "cashflow": {"net_change": 120_000.0}}
    return query, result, dashboard


async def _nl_insight(env: SiteEnv) -> None:
    from app.agents.nl_query_engine import generate_nl_insight
    from app.config import get_settings

    query, result, dashboard = _nl_args(env)
    await generate_nl_insight(query, result, dashboard, [], get_settings())


async def _nl_insight_stream(env: SiteEnv) -> None:
    from app.agents.nl_query_engine import generate_nl_insight_stream
    from app.config import get_settings

    query, result, dashboard = _nl_args(env)
    async for _ in generate_nl_insight_stream(query, result, dashboard, get_settings()):
        pass


_NUMBERS_ONLY = "prompt is numbers/ratios/enum labels only: "

SITES: dict[str, Site] = {
    "agents/coo/orchestrator.py::node_coo_summary": Site(
        _coo_summary, carries=False,
        note=_NUMBERS_ONLY + "overall score, _measured_lines (efficiency /10, utilisation %, breach %, NPS) and risk "
                             "count; alert messages and the bottleneck name stay in top_risks/quick_wins, not the prompt"),
    "agents/coo/process_agent.py::_generate_process_narrative": Site(_process_narrative),
    "agents/coo/resource_agent.py::_generate_resource_narrative": Site(
        _resource_narrative, carries=False,
        note=_NUMBERS_ONLY + "headcount, average utilisation and counts of over/under-utilised teams (team names "
                             "are only counted, never formatted)"),
    "agents/coo/sla_agent.py::_generate_sla_narrative": Site(
        _sla_narrative, carries=False,
        note=_NUMBERS_ONLY + "ticket counts, breach rate, response hours, NPS, trend label, high-risk count"),
    "agents/cto/incident_agent.py::_generate_incident_narrative": Site(_incident_narrative,
        note="@narrative_guard turns the failure into ACIKLAMA_YOK: the figures stay, the explanation is absent"),
    "agents/cto/infra_agent.py::_generate_infra_narrative": Site(_infra_narrative,
        note="@narrative_guard turns the failure into ACIKLAMA_YOK: the figures stay, the explanation is absent"),
    "agents/cto/orchestrator.py::node_cto_summary": Site(_cto_summary),
    "agents/cto/tech_debt_agent.py::_generate_debt_narrative": Site(_debt_narrative,
        note="@narrative_guard turns the failure into ACIKLAMA_YOK: the figures stay, the explanation is absent"),
    "agents/cto/velocity_agent.py::_generate_velocity_narrative": Site(_velocity_narrative,
        note="@narrative_guard turns the failure into ACIKLAMA_YOK: the figures stay, the explanation is absent"),
    "agents/data_ingestion.py::_extract_transactions_with_llm": Site(
        _extract_transactions, reply=_ingestion_reply,
        note="LLMUnavailable is caught inside and returns []; run_data_ingestion also gates the step beforehand"),
    "agents/multi_period_agent.py::_generate_multiperiod_narrative": Site(
        _multiperiod_narrative, carries=False,
        note=_NUMBERS_ONLY + "MoM/YoY percentages and three trend direction labels"),
    "agents/nl_query_engine.py::generate_nl_insight": Site(_nl_insight),
    "agents/nl_query_engine.py::generate_nl_insight_stream": Site(_nl_insight_stream),
    "agents/risk/orchestrator.py::node_risk_summary": Site(_risk_summary),
    "agents/tax_agent.py::_generate_tax_narrative": Site(
        _tax_narrative, carries=False,
        note=_NUMBERS_ONLY + "VAT, withholding, SSI and corporate tax amounts, and a payment calendar of tax-type "
                             "labels with amounts and due dates"),
}
ALIASED: dict[str, str] = {}
