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
from typing import Any

from app.agents.state import AgentRunConfig, CFOState, SkillResult

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

        # S1-4: variance severity classification
        severity = _classify_variance_severity(variance_pct, variance)
        alert_message = _variance_alert_message(cat, variance_pct, variance, budgeted)

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
            "severity": severity,           # "critical" | "warning" | "ok"
            "alert_message": alert_message, # Turkish human-readable message
        })

    # Sort: most over-budget first
    results.sort(key=lambda x: x["variance"], reverse=True)

    total_variance = total_actual - total_budgeted
    total_variance_pct = (total_variance / total_budgeted * 100) if total_budgeted else 0.0

    # Top 3 over-budget items with severity
    critical_items = [r for r in results if r["severity"] == "critical"]
    warning_items  = [r for r in results if r["severity"] == "warning"]

    return {
        "items": results,
        "total_budgeted": total_budgeted,
        "total_actual": total_actual,
        "total_variance": total_variance,
        "total_variance_pct": round(total_variance_pct, 1),
        "over_budget_categories": [r["category"] for r in results if r["status"] == "over"],
        "critical_overruns": [r["category"] for r in critical_items],
        "warning_overruns":  [r["category"] for r in warning_items],
        "period": budget_input.get("period", ""),
        "health_score": _budget_health_score(results),
    }


def _classify_variance_severity(variance_pct: float, variance_cents: int) -> str:
    """Sapma şiddetini sınıflandır."""
    abs_pct = abs(variance_pct)
    if variance_pct > 20 or (variance_pct > 10 and variance_cents > 50_000_00):
        return "critical"   # %20+ aşım veya %10+ + 50K TRY üzeri
    if variance_pct > 10 or variance_cents > 20_000_00:
        return "warning"    # %10+ aşım veya 20K TRY üzeri
    if abs_pct <= 5:
        return "ok"
    return "watch"          # %5-10 arası


def _variance_alert_message(
    category: str, variance_pct: float, variance_cents: int, budgeted: int
) -> str | None:
    """Türkçe sapma uyarı mesajı üret."""
    if variance_pct <= 5:
        return None
    cat_tr = {
        "salary": "Personel giderleri",
        "rent": "Kira",
        "utilities": "Faturalar",
        "marketing": "Pazarlama",
        "technology": "Teknoloji",
        "other_expense": "Diğer giderler",
    }.get(category, category.replace("_", " ").title())

    direction = "aşıldı" if variance_pct > 0 else "altında kaldı"
    return (
        f"{cat_tr} bütçesi %{abs(variance_pct):.1f} {direction} "
        f"(₺{abs(variance_cents)/100:,.0f} fark)."
    )


def _budget_health_score(items: list[dict]) -> float:
    """
    0.0–1.0 bütçe sağlık skoru.
    1.0 = tüm kalemler hedefte, 0.0 = tüm kalemler kritik aşımda.
    """
    if not items:
        return 1.0
    score = 0.0
    for item in items:
        sev = item.get("severity", "ok")
        if sev == "ok":
            score += 1.0
        elif sev == "watch":
            score += 0.7
        elif sev == "warning":
            score += 0.4
        else:  # critical
            score += 0.0
    return round(score / len(items), 3)


async def _generate_budget_narrative(
    budget: dict[str, Any], settings
) -> str:
    try:
        from app.platform.model_gateway import complete_text

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

        text = await complete_text(
            task="metric_commentary",
            system_prompt=(
                "You are a CFO reviewing a budget variance report. "
                "Write a concise management commentary (3-5 sentences). "
                "Highlight the biggest variances, explain likely causes, "
                "and recommend corrective actions."
            ),
            prompt=f"Budget Variance Report:\n{items_text}\n\n{total_line}",
            max_tokens=512,
        )
        return text.strip()
    except Exception as exc:
        logger.debug("LLM budget narrative fallback: %s", exc)
        return (
            f"Total variance is {budget.get('total_variance_pct', 0):+.1f}%. "
            f"{len(budget.get('over_budget_categories', []))} categories are over budget."
        )


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
