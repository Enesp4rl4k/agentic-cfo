"""
Multi-Period Agent — Skill 9.

Sorumluluk: Dönemler arası finansal karşılaştırma.
- MoM (Month-over-Month): Bu ay vs geçen ay
- YoY (Year-over-Year): Bu ay vs geçen yılın aynı ayı
- Trend yönü: son 3 aylık trend (improving/stable/declining)
- KPI büyüme oranları

Veri kaynağı: state['transactions'] — tarihli işlemler.
Birden fazla aylık veri varsa karşılaştırma yapılır.

done_when: state['multi_period'] contains mom, trend_direction
"""
from __future__ import annotations

import logging
import statistics
from collections import defaultdict
from typing import Any

from app.agents.state import CFOState, AgentRunConfig, SkillResult

logger = logging.getLogger(__name__)


# ── Monthly aggregation ───────────────────────────────────────────────────────

def _aggregate_by_month(
    transactions: list[dict[str, Any]]
) -> dict[str, dict[str, int]]:
    """
    Returns dict: month_key → {revenue, expenses, net, opex, salary, ...}
    """
    monthly: dict[str, dict[str, int]] = defaultdict(lambda: {
        "revenue": 0, "expenses": 0, "net": 0,
        "salary": 0, "rent": 0, "utilities": 0,
        "marketing": 0, "technology": 0, "cogs": 0,
        "other_expense": 0, "tax": 0, "loan": 0,
    })

    for tx in transactions:
        date = tx.get("transaction_date", "")
        if not date:
            continue
        month_key = str(date)[:7]  # YYYY-MM
        amount = tx.get("amount_cents", 0)
        cat = tx.get("category", "other_expense")
        tx_type = tx.get("type", "expense")

        if tx_type == "income":
            monthly[month_key]["revenue"] += amount
        else:
            monthly[month_key]["expenses"] += amount
            if cat in monthly[month_key]:
                monthly[month_key][cat] += amount

        monthly[month_key]["net"] = (
            monthly[month_key]["revenue"] - monthly[month_key]["expenses"]
        )

    return dict(monthly)


def _pct_change(current: int, previous: int) -> float | None:
    if previous == 0:
        return None
    return round((current - previous) / previous * 100, 1)


def _compute_mom(
    monthly: dict[str, dict[str, int]]
) -> dict[str, Any] | None:
    """Month-over-Month comparison for the two most recent months."""
    if len(monthly) < 2:
        return None

    sorted_months = sorted(monthly.keys())
    current_month = sorted_months[-1]
    prev_month = sorted_months[-2]

    curr = monthly[current_month]
    prev = monthly[prev_month]

    return {
        "current_month": current_month,
        "previous_month": prev_month,
        "revenue_change_pct": _pct_change(curr["revenue"], prev["revenue"]),
        "expenses_change_pct": _pct_change(curr["expenses"], prev["expenses"]),
        "net_change_pct": _pct_change(curr["net"], prev["net"]),
        "revenue_current": curr["revenue"],
        "revenue_previous": prev["revenue"],
        "net_current": curr["net"],
        "net_previous": prev["net"],
    }


def _compute_yoy(
    monthly: dict[str, dict[str, int]]
) -> dict[str, Any] | None:
    """Year-over-Year: most recent month vs same month last year."""
    if not monthly:
        return None

    sorted_months = sorted(monthly.keys())
    current_month = sorted_months[-1]

    # Find same month last year
    try:
        year, month = int(current_month[:4]), int(current_month[5:7])
        last_year_month = f"{year - 1:04d}-{month:02d}"
    except (ValueError, IndexError):
        return None

    if last_year_month not in monthly:
        return None

    curr = monthly[current_month]
    prev = monthly[last_year_month]

    return {
        "current_month": current_month,
        "year_ago_month": last_year_month,
        "revenue_yoy_pct": _pct_change(curr["revenue"], prev["revenue"]),
        "expenses_yoy_pct": _pct_change(curr["expenses"], prev["expenses"]),
        "net_yoy_pct": _pct_change(curr["net"], prev["net"]),
    }


def _compute_trend(
    monthly: dict[str, dict[str, int]],
    key: str = "net",
    window: int = 3,
) -> str:
    """
    Determine trend direction for the last N months.
    Returns: 'improving' | 'declining' | 'stable' | 'insufficient_data'
    """
    sorted_months = sorted(monthly.keys())
    if len(sorted_months) < window:
        return "insufficient_data"

    recent = [monthly[m][key] for m in sorted_months[-window:]]

    # Simple linear regression slope sign
    n = len(recent)
    x_mean = (n - 1) / 2
    y_mean = statistics.mean(recent)
    numerator = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(recent))
    denominator = sum((i - x_mean) ** 2 for i in range(n))

    if denominator == 0:
        return "stable"

    slope = numerator / denominator
    threshold = abs(y_mean) * 0.05  # 5% of mean = meaningful change

    if slope > threshold:
        return "improving"
    elif slope < -threshold:
        return "declining"
    else:
        return "stable"


def _compute_kpi_trends(
    monthly: dict[str, dict[str, int]]
) -> dict[str, str]:
    """Trend direction for each major KPI."""
    return {
        "revenue_trend": _compute_trend(monthly, "revenue"),
        "expense_trend": _compute_trend(monthly, "expenses"),
        "net_trend": _compute_trend(monthly, "net"),
    }


async def _generate_multiperiod_narrative(
    multi: dict[str, Any], settings
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

    mom = multi.get("mom") or {}
    yoy = multi.get("yoy") or {}
    trends = multi.get("kpi_trends") or {}

    mom_text = (
        f"MoM: revenue {mom.get('revenue_change_pct', 'N/A')}%, "
        f"net {mom.get('net_change_pct', 'N/A')}%"
        if mom else "MoM: insufficient data"
    )
    yoy_text = (
        f"YoY: revenue {yoy.get('revenue_yoy_pct', 'N/A')}%, "
        f"net {yoy.get('net_yoy_pct', 'N/A')}%"
        if yoy else "YoY: insufficient data"
    )
    trend_text = (
        f"Trends (3-month): revenue={trends.get('revenue_trend')}, "
        f"expenses={trends.get('expense_trend')}, "
        f"net={trends.get('net_trend')}"
    )

    messages = [
        SystemMessage(content=(
            "You are a CFO reviewing period-over-period financial performance. "
            "Write a concise performance commentary (3-4 sentences). "
            "Comment on growth trajectory, efficiency, and any concerns."
        )),
        HumanMessage(content=f"{mom_text}\n{yoy_text}\n{trend_text}"),
    ]
    response = await llm.ainvoke(messages)
    return response.content.strip()


# ── Entry point ───────────────────────────────────────────────────────────────

async def run_multi_period(
    state: CFOState,
    config: AgentRunConfig,
) -> SkillResult:
    """
    Multi-Period Skill.
    done_when: state['multi_period']['trend_direction'] is set.
    """
    transactions = state.get("transactions", [])
    if not transactions:
        return SkillResult(
            ok=True,
            patch={"multi_period": None},
            confidence=1.0,
            detail="No transactions — multi-period analysis skipped.",
        )

    try:
        from app.config import get_settings
        settings = get_settings()

        monthly = _aggregate_by_month(transactions)

        if len(monthly) < 2:
            return SkillResult(
                ok=True,
                patch={"multi_period": None},
                confidence=1.0,
                detail="Only 1 month of data — multi-period comparison requires 2+.",
            )

        mom = _compute_mom(monthly)
        yoy = _compute_yoy(monthly)
        kpi_trends = _compute_kpi_trends(monthly)
        overall_trend = _compute_trend(monthly, "net")

        multi = {
            "months_available": len(monthly),
            "month_range": f"{min(monthly.keys())} to {max(monthly.keys())}",
            "mom": mom,
            "yoy": yoy,
            "kpi_trends": kpi_trends,
            "trend_direction": overall_trend,
            "monthly_summary": {
                m: {
                    "revenue": v["revenue"],
                    "expenses": v["expenses"],
                    "net": v["net"],
                }
                for m, v in sorted(monthly.items())
            },
        }

        narrative = await _generate_multiperiod_narrative(multi, settings)
        multi["narrative"] = narrative

        logger.info(
            "Multi-period analysis: job=%s months=%d trend=%s",
            state.get("job_id"), len(monthly), overall_trend,
        )

        return SkillResult(
            ok=True,
            patch={"multi_period": multi},
            confidence=0.90,
            detail=(
                f"Multi-period: {len(monthly)} months, "
                f"trend={overall_trend}, "
                f"MoM net={mom.get('net_change_pct', 'N/A')}%"
            ),
        )

    except Exception as exc:
        logger.exception("Multi-period agent failed for job=%s", state.get("job_id"))
        return SkillResult(ok=False, detail=f"Multi-period error: {exc}")
