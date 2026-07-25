"""
Budget Agent — Skill 7.

Sorumluluk: Kullanıcının yüklediği bütçe verisi ile gerçekleşen
işlemleri karşılaştırır. Sapmaları (variance) hesaplar ve LLM ile
CFO yorumu üretir.

Bütçe verisi iki yoldan gelebilir:
1. state['budget_input'] — dict olarak önceden yüklendiyse
2. Yükleme sırasında ayrı bir bütçe dosyası belirtildiyse

done_when: state['budget'] contains items, total_variance, narrative
"""
from __future__ import annotations

import logging
import statistics
from typing import Any

from app.agents.state import CFOState, AgentRunConfig, SkillResult

logger = logging.getLogger(__name__)


# ── Pure calculations ─────────────────────────────────────────────────────────

def _compute_budget_variance(
    transactions: list[dict[str, Any]],
    budget_input: dict[str, Any],
) -> dict[str, Any]:
    """
    budget_input format:
    {
      "items": [
        {"category": "salary", "budgeted": 500000},   # in cents
        {"category": "rent",   "budgeted": 150000},
        ...
      ],
      "period": "2024-01"   # optional
    }
    """
    budget_items = budget_input.get("items", [])
    if not budget_items:
        return {}

    # Sum actuals per category
    actuals: dict[str, int] = {}
    for tx in transactions:
        if tx.get("type") == "expense":
            cat = tx.get("category", "other_expense")
            actuals[cat] = actuals.get(cat, 0) + tx.get("amount_cents", 0)

    results = []
    total_budgeted = 0
    total_actual = 0

    for item in budget_items:
        cat = item.get("category", "")
        budgeted = item.get("budgeted", 0)
        actual = actuals.get(cat, 0)
        variance = actual - budgeted       # positive = over budget
        variance_pct = (variance / budgeted * 100) if budgeted else 0.0

        total_budgeted += budgeted
        total_actual += actual

        results.append({
            "category": cat,
            "budgeted": budgeted,
            "actual": actual,
            "variance": variance,
            "variance_pct": round(variance_pct, 1),
            "status": (
                "over" if variance > 0
                else "under" if variance < 0
                else "on_target"
            ),
        })

    # Sort: most over-budget first
    results.sort(key=lambda x: x["variance"], reverse=True)

    total_variance = total_actual - total_budgeted
    total_variance_pct = (total_variance / total_budgeted * 100) if total_budgeted else 0.0

    return {
        "items": results,
        "total_budgeted": total_budgeted,
        "total_actual": total_actual,
        "total_variance": total_variance,
        "total_variance_pct": round(total_variance_pct, 1),
        "over_budget_categories": [r["category"] for r in results if r["status"] == "over"],
        "period": budget_input.get("period", ""),
    }


async def _generate_budget_narrative(
    budget: dict[str, Any], settings
) -> str:
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import HumanMessage, SystemMessage

    llm = ChatOpenAI(
        model=settings.llm_model,
        temperature=0.2,
        max_tokens=512,
        api_key=settings.openai_api_key,
        base_url=settings.llm_base_url or None,
    )

    items_text = "\n".join(
        f"- {r['category'].replace('_', ' ').title()}: "
        f"budgeted ${r['budgeted']/100:,.0f} / "
        f"actual ${r['actual']/100:,.0f} / "
        f"variance {r['variance_pct']:+.1f}% ({'OVER' if r['status'] == 'over' else 'UNDER' if r['status'] == 'under' else 'ON TARGET'})"
        for r in budget.get("items", [])[:10]
    )
    total_line = (
        f"Total: budgeted ${budget['total_budgeted']/100:,.0f} / "
        f"actual ${budget['total_actual']/100:,.0f} / "
        f"variance {budget['total_variance_pct']:+.1f}%"
    )

    messages = [
        SystemMessage(content=(
            "You are a CFO reviewing a budget variance report. "
            "Write a concise management commentary (3-5 sentences). "
            "Highlight the biggest variances, explain likely causes, "
            "and recommend corrective actions."
        )),
        HumanMessage(content=f"Budget Variance Report:\n{items_text}\n\n{total_line}"),
    ]
    response = await llm.ainvoke(messages)
    return response.content.strip()


# ── Entry point ───────────────────────────────────────────────────────────────

async def run_budget(
    state: CFOState,
    config: AgentRunConfig,
) -> SkillResult:
    """
    Budget Skill.
    done_when: state['budget'] is populated OR skipped if no budget_input.
    """
    budget_input = state.get("budget_input")  # type: ignore[misc]
    if not budget_input:
        # No budget provided — skip gracefully, not a failure
        return SkillResult(
            ok=True,
            patch={"budget": None},
            confidence=1.0,
            detail="No budget input provided — budget comparison skipped.",
        )

    transactions = state.get("transactions", [])
    if not transactions:
        return SkillResult(
            ok=True,
            patch={"budget": None},
            confidence=1.0,
            detail="No transactions — budget comparison skipped.",
        )

    try:
        from app.config import get_settings
        settings = get_settings()

        budget = _compute_budget_variance(transactions, budget_input)
        if not budget:
            return SkillResult(
                ok=True,
                patch={"budget": None},
                confidence=1.0,
                detail="Budget input had no items.",
            )

        narrative = await _generate_budget_narrative(budget, settings)
        budget["narrative"] = narrative

        over_count = len(budget.get("over_budget_categories", []))
        total_var_pct = budget.get("total_variance_pct", 0)

        return SkillResult(
            ok=True,
            patch={"budget": budget},
            confidence=0.95,
            detail=(
                f"Budget comparison: total variance {total_var_pct:+.1f}%, "
                f"{over_count} categories over budget"
            ),
        )

    except Exception as exc:
        logger.exception("Budget agent failed for job=%s", state.get("job_id"))
        return SkillResult(ok=False, detail=f"Budget error: {exc}")
