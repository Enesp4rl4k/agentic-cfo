"""
Chat Agent — Skill 11 (standalone, pipeline dışı).

Sorumluluk: Finansal + teknoloji verileri üzerinde doğal dil soru-cevap.
- Dashboard JSON + transactions kullanarak bağlamsal yanıt verir
- CEO/CTO pipeline çıktılarını da bağlama ekler
- Senaryo simülasyonu: "Kira %20 artarsa ne olur?"
- Karşılaştırma soruları: "En pahalı kategori hangisi?"
- Tahmin soruları: "3 ay sonra nakit pozisyonum ne olur?"
- Kurumsal soru: "En büyük cross-domain riskimiz nedir?"

Pipeline'a bağlı değil — HTTP endpoint üzerinden çağrılır.
Veri kaynağı: DB'den çekilen job dashboard JSON + transactions + isteğe bağlı CEO/CTO context

done_when: yanıt üretildi (streaming veya tek seferlik)
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from app.agents.chat_money import (
    CURRENCY_RULE,
    FigureCurrency,
    amount,
    amount_tr,
    currency_lines,
    figure_currency,
)
from app.core.currency_totals import fmt_amount
from app.core.turkish import fold
from app.services.runway_display import PROMPT_RULE, view_from_fin

logger = logging.getLogger(__name__)


# ── Financial context builder ─────────────────────────────────────────────────

def _build_financial_context(
    dashboard: dict[str, Any],
    transactions: list[dict[str, Any]],
    max_transactions: int = 30,
) -> str:
    """
    Finansal verileri LLM'e verilecek bağlam metnine dönüştürür.
    """
    pnl = dashboard.get("pnl", {})
    cashflow = dashboard.get("cashflow", {})
    forecast = dashboard.get("forecast", {})
    anomalies = dashboard.get("anomalies", [])

    # The stored dashboard is in major units (report_agent._fmt). This divided by 100
    # again: the model read revenue of ₺97,995 for a company with ₺9,799,500
    # and answered from it (plan v9 §K0). Transactions below are kuruş.
    # The label is the currency the dashboard states (`pnl.currency`), never a default: see chat_money.
    cur = figure_currency(pnl, cashflow, dashboard.get("currency_scope"))

    def fmt(lira: float | int) -> str:
        return amount(lira, cur)

    lines = [
        "=== FINANCIAL SUMMARY ===",
        *currency_lines(cur),
        f"Revenue: {fmt(pnl.get('revenue', 0))}",
        f"Gross Profit: {fmt(pnl.get('gross_profit', 0))} ({pnl.get('gross_margin', 0)*100:.1f}%)",
        f"EBITDA: {fmt(pnl.get('ebitda', 0))} ({pnl.get('ebitda_margin', 0)*100:.1f}%)",
        f"Net Income: {fmt(pnl.get('net_income', 0))} ({pnl.get('net_margin', 0)*100:.1f}%)",
        "",
        "=== OPERATING EXPENSES ===",
    ]

    for cat, spent in (pnl.get("opex") or {}).items():
        if spent and spent > 0:
            lines.append(f"  {cat.replace('_', ' ').title()}: {fmt(spent)}")

    lines += [
        "",
        "=== CASH FLOW ===",
        f"Operating: {fmt(cashflow.get('operating', 0))}",
        f"Investing: {fmt(cashflow.get('investing', 0))}",
        f"Financing: {fmt(cashflow.get('financing', 0))}",
        f"Net Change: {fmt(cashflow.get('net_change', 0))}",
        "",
        "=== 12-MONTH FORECAST (BASE SCENARIO) ===",
    ]

    base = (forecast.get("scenarios") or {}).get("base", {})
    if base:
        lines += [
            f"12-Month Net: {fmt(base.get('twelve_month_net', 0))}",
            f"Cash Runway: {_runway_line(forecast)}",
        ]

    if anomalies:
        critical = [a for a in anomalies if a.get("severity") == "critical"]
        lines += [
            "",
            f"=== ANOMALIES ({len(anomalies)} total, {len(critical)} critical) ===",
        ]
        for a in anomalies[:5]:
            lines.append(f"  [{a['severity'].upper()}] {a['title']}")

    # Recent transactions sample
    if transactions:
        lines += ["", f"=== RECENT TRANSACTIONS (last {min(len(transactions), max_transactions)}) ==="]
        for tx in sorted(
            transactions,
            key=lambda t: t.get("transaction_date") or "",
            reverse=True
        )[:max_transactions]:
            lines.append(
                f"  {(tx.get('transaction_date') or '')[:10]} | "
                f"{tx.get('type', '')} | "
                f"{tx.get('category', '')} | "
                # A row is in its own currency; one that names none is written bare.
                f"{fmt_amount(tx.get('amount_cents', 0) / 100, tx.get('currency'))} | "
                f"{tx.get('description', '')[:40]}"
            )

    return "\n".join(lines)


# ── Answers that need no model ────────────────────────────────────────────────

_NICEL = ("ne kadar", "kac", "toplam", "hangisi", "nedir", "en buyuk")
_GIDER_ADI = {
    "salary": "maaş ve ücretler", "rent": "kira", "utilities": "elektrik, su ve iletişim",
    "marketing": "pazarlama", "technology": "teknoloji", "other_expense": "diğer giderler",
}


def _pnl_cevabi(soru: str, pnl: dict[str, Any], cur: FigureCurrency) -> str | None:
    for anahtarlar, alan, ad in (
        (("favok", "ebitda"), "ebitda", "FAVÖK"),
        (("net kar", "net income"), "net_income", "Net kâr"),
        (("gelir", "ciro", "revenue"), "revenue", "Toplam gelir"),
    ):
        if any(a in soru for a in anahtarlar) and isinstance(pnl.get(alan), (int, float)):
            return f"{ad}: {amount_tr(pnl[alan], cur)}."
    return None


def _en_buyuk_gider(pnl: dict[str, Any], cur: FigureCurrency) -> str | None:
    kalemler = dict(pnl.get("opex") or {})
    if isinstance(pnl.get("cogs"), (int, float)):
        kalemler["cogs"] = pnl["cogs"]
    kalemler = {k: v for k, v in kalemler.items() if isinstance(v, (int, float)) and v > 0}
    if not kalemler:
        return None
    en = max(kalemler, key=lambda k: kalemler[k])
    ad = "satılan malın maliyeti" if en == "cogs" else _GIDER_ADI.get(en, en.replace("_", " "))
    return f"En büyük gider kalemi {ad}: {amount_tr(kalemler[en], cur)}."


def _runway_line(forecast: dict[str, Any]) -> str:
    """The runway as the stored forecast says it: a figure with its basis, or why there is none."""
    runway = forecast.get("runway") or {}
    if runway.get("message"):
        return str(runway["message"])
    ay = ((forecast.get("scenarios") or {}).get("base") or {}).get("runway_months")
    return f"{ay} months" if ay is not None else "not computed"


def _runway_cevabi(dashboard: dict[str, Any]) -> str | None:
    forecast = dashboard.get("forecast") or {}
    base = (forecast.get("scenarios") or {}).get("base")
    if not base:
        return None
    runway = forecast.get("runway") or {}
    if runway.get("message"):
        # The sentence names the balance, its date and the burn it rests on, or says there is none.
        return str(runway["message"])
    ay = base.get("runway_months")
    if isinstance(ay, (int, float)):
        return f"Baz senaryoda nakit pisti: {ay:.1f} ay."
    return "Bu analizde nakit pisti hesaplanmadı."


def dogrudan_cevap(soru: str, dashboard: dict[str, Any]) -> str | None:
    """The answer to a question the stored analysis settles, without a model.

    Only "how much / which" questions: "Geliri nasıl artırırım?" mentions revenue
    but is not asking for the figure, and answering it with one would mislead.
    None means a model is needed.
    """
    s = fold(soru)
    pnl = dashboard.get("pnl") or {}
    cur = figure_currency(pnl, dashboard.get("cashflow"), dashboard.get("currency_scope"))
    if "runway" in s or "nakit pist" in s:
        return _runway_cevabi(dashboard)
    if not any(k in s for k in _NICEL):
        return None
    if "gider" in s and "en buyuk" in s:
        return _en_buyuk_gider(pnl, cur)
    return _pnl_cevabi(s, pnl, cur)


# ── CEO/CTO context builder ───────────────────────────────────────────────────

def _build_executive_context(
    ceo_result: dict[str, Any] | None = None,
    cto_result: dict[str, Any] | None = None,
) -> str:
    """
    CEO/CTO pipeline çıktılarından LLM bağlamı oluşturur.
    Her ikisi de opsiyonel — mevcut olan eklenir.
    """
    lines: list[str] = []

    if cto_result:
        summary = cto_result.get("cto_summary") or {}
        infra = cto_result.get("infra") or {}
        tech_debt = cto_result.get("tech_debt") or {}
        incidents = cto_result.get("incidents") or {}
        velocity = cto_result.get("velocity") or {}

        lines += [
            "=== TECHNOLOGY HEALTH (CTO VIEW) ===",
            f"Overall Health Score: {summary.get('overall_health_score', 'N/A')}/10",
        ]

        if infra:
            lines.append(
                # The infrastructure figures state no currency (cloud bills often are not in the company's):
                # written bare, and said so.
                f"Infrastructure Cost: {fmt_amount(infra.get('total_cost_cents', 0)/100, None)}/month"
                f" | Waste: {fmt_amount(infra.get('waste_estimate_cents', 0)/100, None)}"
                " (currency not stated in the source data)"
            )

        if tech_debt:
            lines.append(
                f"Tech Debt Score: {tech_debt.get('debt_score', 'N/A')}/10"
                f" | Hotspot Files: {len(tech_debt.get('hotspot_files', []))}"
            )

        if incidents:
            lines.append(
                f"Incidents: {incidents.get('total_incidents', 0)} total"
                f" | MTTR: {incidents.get('mttr_hours', 'N/A')}h"
                f" | SLA Breaches: {incidents.get('sla_breach_count', 0)}"
            )

        if velocity:
            lines.append(
                f"Engineering Velocity: {velocity.get('avg_velocity', 0)} pts/sprint"
                f" | Trend: {velocity.get('velocity_trend', 'N/A')}"
                f" | Predictability: {velocity.get('predictability_score', 0)*100:.0f}%"
            )

        top_risks = summary.get("top_risks", [])[:3]
        if top_risks:
            lines += ["", "Top Tech Risks:"]
            for r in top_risks:
                lines.append(f"  [{r.get('severity','').upper()}] {r.get('domain','')}: {r.get('message','')}")

        if summary.get("narrative"):
            lines += ["", f"CTO Assessment: {summary['narrative']}"]

        lines.append("")

    if ceo_result:
        cross_risks = ceo_result.get("cross_risks") or []
        priorities = ceo_result.get("strategic_priorities") or []
        fin_summary = ceo_result.get("financial_summary") or {}
        tech_summary = ceo_result.get("tech_summary") or {}
        board_deck = ceo_result.get("board_deck") or {}

        lines += ["=== CROSS-DOMAIN CEO ANALYSIS ==="]

        if fin_summary:
            cur = figure_currency(fin_summary)
            lines += [
                *currency_lines(cur),
                f"Revenue: {amount(fin_summary.get('revenue_cents', 0)/100, cur)}",
                f"Net Income: {amount(fin_summary.get('net_income_cents', 0)/100, cur)}"
                f" ({fin_summary.get('net_margin', 0)*100:.1f}% margin)",
                f"Cash Runway: {view_from_fin(fin_summary).text()}",
                PROMPT_RULE,
            ]

        if tech_summary:
            lines.append(
                f"Tech Health: {tech_summary.get('overall_health_score', 'N/A')}/10"
            )

        if cross_risks:
            lines += ["", f"Cross-Domain Risks ({len(cross_risks)}):"]
            for r in cross_risks[:5]:
                lines.append(
                    f"  [{r.get('severity','').upper()}] {r.get('title','')}"
                    f" — {r.get('recommended_action','')[:80]}"
                )

        if priorities:
            lines += ["", f"Strategic Priorities ({len(priorities)}):"]
            for p in priorities[:5]:
                lines.append(
                    f"  {p.get('rank','')}.  [{p.get('urgency','').upper()}] {p.get('action','')}"
                    f" (Owner: {p.get('owner','')})"
                )

        if board_deck.get("one_page_summary"):
            lines += ["", f"Board Summary: {board_deck['one_page_summary'][:300]}"]

    return "\n".join(lines)


# ── System prompts ────────────────────────────────────────────────────────────

CFO_SYSTEM_PROMPT = """You are an expert AI CFO assistant. You have access to the company's
financial data provided below. Answer questions accurately and concisely.

Guidelines:
- Use the financial data provided — don't make up numbers
- When doing "what-if" scenarios, clearly label them as hypothetical
- {currency_rule}
- Be direct and actionable — you're talking to a CFO or business owner
- If data is insufficient to answer, say so clearly
- Respond in the same language as the question

Financial Data:
{context}
"""

CEO_SYSTEM_PROMPT = """You are an expert AI advisor to the CEO. You have access to both
financial (CFO) and technology (CTO) data for the company, plus cross-domain analysis.
Answer strategic questions by synthesizing both domains.

Guidelines:
- Always think cross-domain: financial risks often have tech causes and vice versa
- Prioritize by urgency and financial impact
- Be direct and executive-level — no jargon, clear recommendations
- {currency_rule}; format scores as X/10
- If data is missing for one domain, still answer with available data
- Respond in the same language as the question

Company Data:
{context}
"""


# ── Main chat functions ───────────────────────────────────────────────────────

async def chat_with_cfo(
    question: str,
    dashboard: dict[str, Any],
    transactions: list[dict[str, Any]],
    conversation_history: list[dict[str, str]] | None = None,
    system_prompt_override: str | None = None,
) -> str:
    """
    Single-turn or multi-turn CFO chat.

    Args:
        question: User's question
        dashboard: Dashboard JSON from the report agent
        transactions: List of transaction dicts
        conversation_history: Previous turns [{"role": "user/assistant", "content": "..."}]
        system_prompt_override: If set, replaces the default CFO system prompt entirely.
            Used by /chat/agent to inject full CompanyContext across all agents.

    Returns:
        Assistant's response text
    """
    from app.platform.model_gateway import complete_text

    if system_prompt_override:
        system_content = system_prompt_override
    else:
        context = _build_financial_context(dashboard, transactions)
        system_content = CFO_SYSTEM_PROMPT.format(context=context, currency_rule=CURRENCY_RULE)

    return (await complete_text(
        task="deep_analysis",
        system_prompt=system_content,
        prompt=question,
        history=conversation_history,
        max_tokens=1024,
    )).strip()


async def chat_with_ceo(
    question: str,
    ceo_result: dict[str, Any] | None = None,
    cto_result: dict[str, Any] | None = None,
    dashboard: dict[str, Any] | None = None,
    transactions: list[dict[str, Any]] | None = None,
    conversation_history: list[dict[str, str]] | None = None,
) -> str:
    """
    CEO-level chat: synthesizes financial + technology context.

    Can be called with any combination of:
    - ceo_result: full CEO pipeline output (cross_risks, priorities, board_deck)
    - cto_result: CTO pipeline output (infra, tech_debt, incidents, velocity)
    - dashboard + transactions: CFO pipeline output (fallback)

    Returns:
        Assistant's response text
    """
    from app.platform.model_gateway import complete_text

    context_parts: list[str] = []
    if dashboard:
        context_parts.append(_build_financial_context(dashboard, transactions or []))
    exec_ctx = _build_executive_context(ceo_result=ceo_result, cto_result=cto_result)
    if exec_ctx.strip():
        context_parts.append(exec_ctx)
    context = "\n\n".join(context_parts) if context_parts else "No data available."

    return (await complete_text(
        task="deep_analysis",
        system_prompt=CEO_SYSTEM_PROMPT.format(context=context, currency_rule=CURRENCY_RULE),
        prompt=question,
        history=conversation_history,
        max_tokens=1024,
    )).strip()


async def stream_chat_with_cfo(
    question: str,
    dashboard: dict[str, Any],
    transactions: list[dict[str, Any]],
    conversation_history: list[dict[str, str]] | None = None,
    system_prompt_override: str | None = None,
) -> AsyncIterator[str]:
    """Streaming CFO chat — yields text chunks."""
    from app.platform.model_gateway import stream as _gw_stream

    if system_prompt_override:
        system_content = system_prompt_override
    else:
        context = _build_financial_context(dashboard, transactions)
        system_content = CFO_SYSTEM_PROMPT.format(context=context, currency_rule=CURRENCY_RULE)

    async for piece in _gw_stream(
        task="deep_analysis",
        system_prompt=system_content,
        prompt=question,
        history=conversation_history,
        max_tokens=1024,
    ):
        yield piece


async def stream_chat_with_ceo(
    question: str,
    ceo_result: dict[str, Any] | None = None,
    cto_result: dict[str, Any] | None = None,
    dashboard: dict[str, Any] | None = None,
    transactions: list[dict[str, Any]] | None = None,
    conversation_history: list[dict[str, str]] | None = None,
) -> AsyncIterator[str]:
    """Streaming CEO chat — yields text chunks."""
    from app.platform.model_gateway import stream as _gw_stream

    context_parts: list[str] = []
    if dashboard:
        context_parts.append(_build_financial_context(dashboard, transactions or []))
    exec_ctx = _build_executive_context(ceo_result=ceo_result, cto_result=cto_result)
    if exec_ctx.strip():
        context_parts.append(exec_ctx)
    context = "\n\n".join(context_parts) if context_parts else "No data available."

    async for piece in _gw_stream(
        task="deep_analysis",
        system_prompt=CEO_SYSTEM_PROMPT.format(context=context, currency_rule=CURRENCY_RULE),
        prompt=question,
        history=conversation_history,
        max_tokens=1024,
    ):
        yield piece
