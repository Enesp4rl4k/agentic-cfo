"""
P&L Agent — Skill 2 of 5.

Responsibility: Compute the Profit & Loss statement from extracted transactions.
Calculates: Revenue, COGS, Gross Profit, OpEx breakdown, EBITDA, Net Income.
Also asks GPT-4o for a CFO-level narrative summary.

done_when: state['pnl'] contains revenue, gross_profit, net_income (all integers in cents).
"""
from __future__ import annotations

from app.services.telemetry import trace_agent

import logging
from typing import Any

from app.agents.state import CFOState, AgentRunConfig, SkillResult
from app.config import get_settings

logger = logging.getLogger(__name__)


def _fmt(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def _compute_pnl(transactions: list[dict[str, Any]]) -> dict[str, Any]:
    """Pure calculation — no LLM, no I/O."""
    income_txs = [t for t in transactions if t.get("type") == "income"]
    expense_txs = [t for t in transactions if t.get("type") == "expense"]

    revenue = sum(t.get("amount_cents", 0) for t in income_txs)
    cogs = sum(t.get("amount_cents", 0) for t in expense_txs if t.get("category") == "cogs")
    gross_profit = revenue - cogs
    gross_margin = round(gross_profit / revenue, 4) if revenue else 0.0

    opex_categories = ["salary", "rent", "utilities", "marketing", "technology", "other_expense"]
    opex_by_category = {
        cat: sum(t.get("amount_cents", 0) for t in expense_txs if t.get("category") == cat)
        for cat in opex_categories
    }
    total_opex = sum(opex_by_category.values())

    ebitda = gross_profit - total_opex
    ebitda_margin = round(ebitda / revenue, 4) if revenue else 0.0

    tax = sum(t.get("amount_cents", 0) for t in expense_txs if t.get("category") == "tax")
    loan_payments = sum(t.get("amount_cents", 0) for t in expense_txs if t.get("category") == "loan")
    net_income = ebitda - tax - loan_payments
    net_margin = round(net_income / revenue, 4) if revenue else 0.0

    return {
        "revenue": revenue,
        "cogs": cogs,
        "gross_profit": gross_profit,
        "gross_margin": gross_margin,
        "opex": opex_by_category,
        "total_opex": total_opex,
        "ebitda": ebitda,
        "ebitda_margin": ebitda_margin,
        "tax": tax,
        "loan_payments": loan_payments,
        "net_income": net_income,
        "net_margin": net_margin,
        "total_expenses": cogs + total_opex + tax + loan_payments,
        "transaction_count": len(transactions),
    }


async def _generate_cfo_narrative(
    pnl: dict[str, Any],
    settings,
    sector: str = "default",
    state: dict[str, Any] | None = None,
) -> str:
    """
    Generate CFO narrative using structured output + ContextBuilder.
    Falls back to template if LLM key is not configured.
    Returns plain text string for backward compatibility with pipeline.
    """
    from app.services.llm_structured import get_pnl_narrative
    from app.services.context_builder import get_context_builder

    # Build benchmark context string
    benchmark_lines: str | None = None
    pnl_with_benchmark = dict(pnl)
    try:
        from app.services.benchmark import get_benchmark_engine
        engine = get_benchmark_engine()
        bm = engine.build_full_comparison(pnl, sector=sector)
        metrics = bm.get("metrics") or {}
        bm_parts = []
        for metric, data in metrics.items():
            if "company_value" in data and "benchmark" in data:
                bm_parts.append(
                    f"{metric}: şirket %{data['company_value']*100:.1f} "
                    f"vs medyan %{data['benchmark']['median']*100:.1f} "
                    f"({data.get('percentile_position', '')})"
                )
        if bm_parts:
            benchmark_lines = "; ".join(bm_parts)
            pnl_with_benchmark["_benchmark_context"] = benchmark_lines
    except Exception:
        pass

    # Use ContextBuilder to assemble token-budgeted prompt context
    if state is not None:
        ctx = get_context_builder(budget=4096)
        context_result = ctx.build_pnl_context(
            state={**state, "pnl": pnl},
            sector=sector,
            benchmark_lines=benchmark_lines,
        )
        # Attach context metadata for observability
        pnl_with_benchmark["_context_tokens"] = context_result.token_count
        pnl_with_benchmark["_context_truncated"] = context_result.truncated

    narrative = await get_pnl_narrative(pnl_with_benchmark, settings)
    return narrative.to_text()


@trace_agent("pnl_agent")
async def run_pnl(state: CFOState, config: AgentRunConfig) -> SkillResult:
    """P&L Skill. done_when: state['pnl']['net_income'] is an integer."""
    transactions = state.get("transactions", [])
    if not transactions:
        return SkillResult(ok=False, detail="No transactions available for P&L calculation.", halt=True)

    try:
        settings = get_settings()
        pnl = _compute_pnl(transactions)
        narrative = await _generate_cfo_narrative(pnl, settings, state=state)
        pnl["narrative"] = narrative

        confidence = 0.95 if pnl["revenue"] > 0 else 0.50

        return SkillResult(
            ok=True,
            patch={"pnl": pnl},
            confidence=confidence,
            detail=(
                f"P&L computed: revenue={_fmt(pnl['revenue'])}, "
                f"net_income={_fmt(pnl['net_income'])}, "
                f"net_margin={pnl['net_margin']*100:.1f}%"
            ),
        )
    except Exception as exc:
        logger.exception("P&L agent failed for job=%s", state.get("job_id"))
        return SkillResult(ok=False, detail=f"P&L error: {exc}", halt=True)
