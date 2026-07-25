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
from typing import Any, AsyncIterator

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

    def fmt(cents: float | int) -> str:
        return f"${cents:,.0f}"

    lines = [
        "=== FINANCIAL SUMMARY ===",
        f"Revenue: {fmt(pnl.get('revenue', 0))}",
        f"Gross Profit: {fmt(pnl.get('gross_profit', 0))} ({pnl.get('gross_margin', 0)*100:.1f}%)",
        f"EBITDA: {fmt(pnl.get('ebitda', 0))} ({pnl.get('ebitda_margin', 0)*100:.1f}%)",
        f"Net Income: {fmt(pnl.get('net_income', 0))} ({pnl.get('net_margin', 0)*100:.1f}%)",
        "",
        "=== OPERATING EXPENSES ===",
    ]

    for cat, amount in (pnl.get("opex") or {}).items():
        if amount and amount > 0:
            lines.append(f"  {cat.replace('_', ' ').title()}: {fmt(amount)}")

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
            f"Cash Runway: {base.get('runway_months', 'Stable')} months",
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
                f"  {tx.get('transaction_date', '')[:10]} | "
                f"{tx.get('type', '')} | "
                f"{tx.get('category', '')} | "
                f"${tx.get('amount_cents', 0) / 100:,.0f} | "
                f"{tx.get('description', '')[:40]}"
            )

    return "\n".join(lines)


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
                f"Infrastructure Cost: ${infra.get('total_cost_cents', 0)/100:,.0f}/month"
                f" | Waste: ${infra.get('waste_estimate_cents', 0)/100:,.0f}"
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
            lines += [
                f"Revenue: ${fin_summary.get('revenue_cents', 0)/100:,.0f}",
                f"Net Income: ${fin_summary.get('net_income_cents', 0)/100:,.0f}"
                f" ({fin_summary.get('net_margin', 0)*100:.1f}% margin)",
                f"Cash Runway: {fin_summary.get('cash_runway_months', 'N/A')} months",
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
- Format currency as $X,XXX
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
- Format currency as $X,XXX; format scores as X/10
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
) -> str:
    """
    Single-turn or multi-turn CFO chat.

    Args:
        question: User's question
        dashboard: Dashboard JSON from the report agent
        transactions: List of transaction dicts
        conversation_history: Previous turns [{"role": "user/assistant", "content": "..."}]

    Returns:
        Assistant's response text
    """
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
    from app.config import get_settings

    settings = get_settings()
    context = _build_financial_context(dashboard, transactions)

    llm = ChatOpenAI(
        model=settings.llm_model,
        temperature=0.1,
        max_tokens=1024,
        api_key=settings.openai_api_key,
        base_url=settings.llm_base_url or None,
    )

    messages = [SystemMessage(content=CFO_SYSTEM_PROMPT.format(context=context))]

    for turn in (conversation_history or []):
        if turn["role"] == "user":
            messages.append(HumanMessage(content=turn["content"]))
        elif turn["role"] == "assistant":
            messages.append(AIMessage(content=turn["content"]))

    messages.append(HumanMessage(content=question))

    response = await llm.ainvoke(messages)
    return response.content.strip()


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
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
    from app.config import get_settings

    settings = get_settings()

    context_parts: list[str] = []

    # Add financial context if available
    if dashboard:
        fin_ctx = _build_financial_context(dashboard, transactions or [])
        context_parts.append(fin_ctx)

    # Add CEO/CTO executive context
    exec_ctx = _build_executive_context(ceo_result=ceo_result, cto_result=cto_result)
    if exec_ctx.strip():
        context_parts.append(exec_ctx)

    context = "\n\n".join(context_parts) if context_parts else "No data available."

    llm = ChatOpenAI(
        model=settings.llm_model,
        temperature=0.1,
        max_tokens=1024,
        api_key=settings.openai_api_key,
        base_url=settings.llm_base_url or None,
    )

    messages = [SystemMessage(content=CEO_SYSTEM_PROMPT.format(context=context))]

    for turn in (conversation_history or []):
        if turn["role"] == "user":
            messages.append(HumanMessage(content=turn["content"]))
        elif turn["role"] == "assistant":
            messages.append(AIMessage(content=turn["content"]))

    messages.append(HumanMessage(content=question))

    response = await llm.ainvoke(messages)
    return response.content.strip()


async def stream_chat_with_cfo(
    question: str,
    dashboard: dict[str, Any],
    transactions: list[dict[str, Any]],
    conversation_history: list[dict[str, str]] | None = None,
) -> AsyncIterator[str]:
    """Streaming CFO chat — yields text chunks."""
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
    from app.config import get_settings

    settings = get_settings()
    context = _build_financial_context(dashboard, transactions)

    llm = ChatOpenAI(
        model=settings.llm_model,
        temperature=0.1,
        max_tokens=1024,
        api_key=settings.openai_api_key,
        base_url=settings.llm_base_url or None,
        streaming=True,
    )

    messages = [SystemMessage(content=CFO_SYSTEM_PROMPT.format(context=context))]
    for turn in (conversation_history or []):
        if turn["role"] == "user":
            messages.append(HumanMessage(content=turn["content"]))
        elif turn["role"] == "assistant":
            messages.append(AIMessage(content=turn["content"]))
    messages.append(HumanMessage(content=question))

    async for chunk in llm.astream(messages):
        if chunk.content:
            yield chunk.content


async def stream_chat_with_ceo(
    question: str,
    ceo_result: dict[str, Any] | None = None,
    cto_result: dict[str, Any] | None = None,
    dashboard: dict[str, Any] | None = None,
    transactions: list[dict[str, Any]] | None = None,
    conversation_history: list[dict[str, str]] | None = None,
) -> AsyncIterator[str]:
    """Streaming CEO chat — yields text chunks."""
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
    from app.config import get_settings

    settings = get_settings()

    context_parts: list[str] = []
    if dashboard:
        context_parts.append(_build_financial_context(dashboard, transactions or []))
    exec_ctx = _build_executive_context(ceo_result=ceo_result, cto_result=cto_result)
    if exec_ctx.strip():
        context_parts.append(exec_ctx)
    context = "\n\n".join(context_parts) if context_parts else "No data available."

    llm = ChatOpenAI(
        model=settings.llm_model,
        temperature=0.1,
        max_tokens=1024,
        api_key=settings.openai_api_key,
        base_url=settings.llm_base_url or None,
        streaming=True,
    )

    messages = [SystemMessage(content=CEO_SYSTEM_PROMPT.format(context=context))]
    for turn in (conversation_history or []):
        if turn["role"] == "user":
            messages.append(HumanMessage(content=turn["content"]))
        elif turn["role"] == "assistant":
            messages.append(AIMessage(content=turn["content"]))
    messages.append(HumanMessage(content=question))

    async for chunk in llm.astream(messages):
        if chunk.content:
            yield chunk.content
