"""
Budget vs Actual Agent — Skill 8 of 8.

Responsibility: Compare actual spend/revenue against a budget baseline.
Identifies over/under-budget categories, computes variance percentages,
and generates a CFO-level action plan.

The budget baseline is passed via AgentRunConfig.budget_baseline:
  { "salary": 500000_00, "marketing": 100000_00, ... }  # all in cents

If no budget_baseline is provided, the agent creates an auto-budget from
the previous period's actuals (simple average × 1.05 growth assumption).

done_when: state['budget_comparison']['categories'] is populated with variances.
"""
from __future__ import annotations

import logging
from typing import Any

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.state import CFOState, AgentRunConfig, SkillResult
from app.config import get_settings

logger = logging.getLogger(__name__)

# Categories tracked for budget comparison
BUDGET_CATEGORIES = [
    "revenue", "cogs", "salary", "rent", "utilities",
    "marketing", "technology", "tax", "loan",
    "other_expense", "other_income",
]

# Auto-budget growth assumption when no baseline provided
AUTO_BUDGET_GROWTH = 1.05  # +5% over actuals as target


def _fmt(cents: int) -> str:
    return f"₺{cents / 100:,.0f}"


def _compute_actuals(transactions: list[dict[str, Any]]) -> dict[str, int]:
    """Sum actual amounts per category (income positive, expense negative)."""
    actuals: dict[str, int] = {cat: 0 for cat in BUDGET_CATEGORIES}
    for tx in transactions:
        cat = tx.get("category", "other_expense")
        amt = tx.get("amount_cents", 0)
        tx_type = tx.get("type", "expense")
        if cat in actuals:
            # Revenue/income categories add, expense categories add too (we track absolute spend)
            actuals[cat] += amt
    return actuals


def _build_auto_budget(actuals: dict[str, int]) -> dict[str, int]:
    """
    Auto-generate a budget from actuals when no baseline is provided.
    Revenue target = actual × 1.05 (growth goal)
    Expense targets = actual × 1.00 (hold the line)
    """
    income_cats = {"revenue", "other_income"}
    budget: dict[str, int] = {}
    for cat, amt in actuals.items():
        if cat in income_cats:
            budget[cat] = int(amt * AUTO_BUDGET_GROWTH)
        else:
            budget[cat] = int(amt * 1.0)  # flat budget = hold spend
    return budget


def _compute_variances(
    actuals: dict[str, int],
    budget: dict[str, int],
) -> dict[str, dict[str, Any]]:
    """
    For each category, compute:
    - budget: planned amount
    - actual: realised amount
    - variance: actual - budget (positive = over for expense = bad; over for revenue = good)
    - variance_pct: variance / budget × 100
    - status: "on_track" | "over_budget" | "under_budget" | "ahead_of_target"
    """
    income_cats = {"revenue", "other_income"}
    categories: dict[str, dict[str, Any]] = {}

    for cat in BUDGET_CATEGORIES:
        bgt = budget.get(cat, 0)
        act = actuals.get(cat, 0)
        variance = act - bgt
        variance_pct = round(variance / max(1, abs(bgt)) * 100, 1)

        if cat in income_cats:
            # For revenue: actual > budget is GOOD
            if variance >= 0:
                status = "ahead_of_target"
            elif variance_pct >= -5:
                status = "on_track"
            else:
                status = "under_budget"
        else:
            # For expenses: actual > budget is BAD
            if variance_pct > 5:
                status = "over_budget"
            elif variance_pct < -5:
                status = "under_spend"
            else:
                status = "on_track"

        categories[cat] = {
            "budget": bgt,
            "actual": act,
            "variance": variance,
            "variance_pct": variance_pct,
            "status": status,
        }

    return categories


def _build_budget_alerts(
    categories: dict[str, dict[str, Any]],
) -> list[dict[str, str]]:
    alerts: list[dict[str, str]] = []

    for cat, data in categories.items():
        if data["status"] == "over_budget" and abs(data["variance"]) > 1000_00:
            alerts.append({
                "level": "warning",
                "message": (
                    f"'{cat}' bütçe aşımı: bütçe {_fmt(data['budget'])}, "
                    f"gerçekleşen {_fmt(data['actual'])} "
                    f"(%{abs(data['variance_pct']):.1f} aşım)."
                ),
                "category": cat,
            })
        elif data["status"] == "under_budget" and abs(data["variance"]) > 1000_00:
            alerts.append({
                "level": "info",
                "message": (
                    f"'{cat}' hedefin altında: hedef {_fmt(data['budget'])}, "
                    f"gerçekleşen {_fmt(data['actual'])} "
                    f"(%{abs(data['variance_pct']):.1f} altında)."
                ),
                "category": cat,
            })

    return alerts


async def _generate_budget_narrative(
    categories: dict[str, dict[str, Any]],
    total_variance: int,
    variance_pct: float,
    alerts: list[dict[str, str]],
    auto_budget: bool,
    lang: str,
    settings,
) -> str:
    from app.agents.i18n import get_language_instruction
    llm = ChatOpenAI(
        model=settings.llm_model,
        temperature=0.2,
        max_tokens=700,
        api_key=settings.openai_api_key,
    )
    lang_instruction = get_language_instruction(lang)
    over = [f"  - {cat}: {d['variance_pct']:.1f}% overrun" for cat, d in categories.items() if d["status"] == "over_budget"]
    under_rev = [f"  - {cat}: {abs(d['variance_pct']):.1f}% below target" for cat, d in categories.items() if d["status"] == "under_budget"]
    ahead = [f"  - {cat}: {d['variance_pct']:.1f}% above target" for cat, d in categories.items() if d["status"] == "ahead_of_target"]

    budget_note = "Note: Budget baseline auto-generated from actuals." if auto_budget else ""

    messages = [
        SystemMessage(content=(
            "You are an experienced CFO. Analyze the budget vs actual comparison "
            "and provide actionable recommendations (4-6 sentences). "
            f"Highlight key variances and priorities. {lang_instruction}"
        )),
        HumanMessage(content=(
            f"Toplam Varyans: {_fmt(total_variance)} (%{variance_pct:.1f})\n"
            f"{budget_note}\n\n"
            + (f"Bütçe Aşan Kategoriler:\n" + "\n".join(over) + "\n\n" if over else "")
            + (f"Hedef Altı Gelir:\n" + "\n".join(under_rev) + "\n\n" if under_rev else "")
            + (f"Hedef Üstü Gelir:\n" + "\n".join(ahead) if ahead else "")
        )),
    ]
    response = await llm.ainvoke(messages)
    return response.content.strip()


async def run_budget_comparison(state: CFOState, config: AgentRunConfig) -> SkillResult:
    """
    Budget vs Actual Skill.
    done_when: state['budget_comparison']['categories'] is a dict with variance data.
    """
    transactions = state.get("transactions", [])
    if not transactions:
        return SkillResult(
            ok=True,
            patch={"budget_comparison": {
                "categories": {}, "total_variance": 0, "variance_pct": 0.0,
                "alerts": [], "narrative": "İşlem verisi yok.",
                "auto_budget": False,
            }},
            confidence=1.0,
            detail="İşlem verisi yok — bütçe karşılaştırması atlandı.",
        )

    try:
        from app.agents.i18n import validate_language
        settings = get_settings()
        lang = validate_language(config.language)
        actuals = _compute_actuals(transactions)

        # Use provided budget or auto-generate
        baseline = config.budget_baseline if config.budget_baseline else None
        auto_budget = baseline is None
        budget = baseline if baseline else _build_auto_budget(actuals)

        categories = _compute_variances(actuals, budget)
        alerts = _build_budget_alerts(categories)

        income_cats = {"revenue", "other_income"}
        total_variance = sum(
            data["variance"] if cat in income_cats else -data["variance"]
            for cat, data in categories.items()
        )
        revenue_budget = budget.get("revenue", 1)
        variance_pct = round(total_variance / max(1, revenue_budget) * 100, 1)

        narrative = await _generate_budget_narrative(
            categories, total_variance, variance_pct, alerts, auto_budget, lang, settings
        )

        budget_comparison = {
            "categories": categories,
            "total_variance": total_variance,
            "variance_pct": variance_pct,
            "auto_budget": auto_budget,
            "over_budget_count": sum(1 for d in categories.values() if d["status"] == "over_budget"),
            "alerts": alerts,
            "narrative": narrative,
        }

        has_critical_overrun = any(
            d["variance_pct"] > 20 for d in categories.values()
            if d["status"] == "over_budget"
        )
        confidence = 0.85 if not has_critical_overrun else 0.78

        return SkillResult(
            ok=True,
            patch={"budget_comparison": budget_comparison},
            confidence=confidence,
            needs_review=has_critical_overrun,
            detail=(
                f"Bütçe karşılaştırması: toplam varyans={_fmt(total_variance)}, "
                f"bütçe aşan={budget_comparison['over_budget_count']} kategori"
            ),
        )
    except Exception as exc:
        logger.exception("Budget agent failed for job=%s", state.get("job_id"))
        return SkillResult(ok=False, detail=f"Bütçe karşılaştırması hatası: {exc}")
