"""
CMO Cohort Agent -- CMO Skill 3 of 3.

Responsibility: Parse user cohort CSV and compute retention rates,
LTV, LTV:CAC ratio, churn rate, and cohort trends.

Supported CSV formats (flexible column detection):
  - Mixpanel export: Cohort, Users, Day 0, Day 30, Day 60, Day 90
  - Amplitude export: cohort_date, users, retention_week_1, retention_month_1
  - Generic: cohort/period, users/size, retention_30d/month_1, retention_90d/month_3, ltv/revenue

done_when: state['cohorts']['ltv_cac_ratio'] is a float
"""
from __future__ import annotations

import csv
import io
import logging
from typing import Any

from app.agents.cmo.state import CMOState

logger = logging.getLogger(__name__)


# ── CSV Parser ────────────────────────────────────────────────────────────────

def _parse_cohort_csv(csv_text: str) -> list[dict[str, Any]]:
    """Parse cohort CSV -- flexible column detection."""
    reader = csv.DictReader(io.StringIO(csv_text.strip()))
    rows: list[dict[str, Any]] = []

    def _col(*candidates: str) -> str | None:
        for c in candidates:
            for k in (reader.fieldnames or []):
                if k.strip().lower().replace(" ", "_").replace("-", "_") == \
                   c.lower().replace(" ", "_"):
                    return k
        return None

    period_col   = _col("cohort", "period", "cohort_date", "month", "week", "date")
    users_col    = _col("users", "size", "cohort_size", "new_users", "customers")
    ret30_col    = _col(
        "retention_30d", "month_1", "retention_month_1", "day_30",
        "30d_retention", "m1_retention", "ret_30",
    )
    ret90_col    = _col(
        "retention_90d", "month_3", "retention_month_3", "day_90",
        "90d_retention", "m3_retention", "ret_90",
    )
    ltv_col      = _col("ltv", "lifetime_value", "revenue", "avg_ltv", "arpu", "value")
    cac_col      = _col("cac", "acquisition_cost", "customer_acquisition_cost", "cost")

    for i, row in enumerate(reader):
        period = (row.get(period_col) or f"Cohort {i+1}").strip()
        users  = 0
        ret30  = None
        ret90  = None
        ltv    = 0.0
        cac    = 0.0

        try:
            users = int(float((row.get(users_col) or "0").replace(",", "")))
        except (ValueError, TypeError):
            pass

        for col, dest in [(ret30_col, "ret30"), (ret90_col, "ret90")]:
            raw = (row.get(col) or "").strip().rstrip("%")
            try:
                val = float(raw.replace(",", ""))
                # Normalize: if value > 1, treat as percentage
                if val > 1:
                    val = val / 100
                if dest == "ret30":
                    ret30 = min(val, 1.0)
                else:
                    ret90 = min(val, 1.0)
            except (ValueError, TypeError):
                pass

        try:
            ltv = float((row.get(ltv_col) or "0").replace(",", "").replace("$", ""))
        except (ValueError, TypeError):
            pass
        try:
            cac = float((row.get(cac_col) or "0").replace(",", "").replace("$", ""))
        except (ValueError, TypeError):
            pass

        rows.append({
            "period":       period,
            "users":        users,
            "retention_30d": ret30,
            "retention_90d": ret90,
            "ltv_cents":    int(ltv * 100),
            "cac_cents":    int(cac * 100),
        })

    return rows


# ── Pure Calculations ─────────────────────────────────────────────────────────

def _compute_cohort_metrics(
    cohorts: list[dict[str, Any]],
    overall_cac_cents: int = 0,
) -> dict[str, Any]:
    """Pure calculation -- no LLM."""
    if not cohorts:
        return {
            "cohorts_analyzed": 0,
            "avg_retention_30d": 0.0,
            "avg_retention_90d": 0.0,
            "avg_ltv_cents": 0,
            "ltv_cac_ratio": 0.0,
            "churn_rate": 0.0,
            "best_cohort": None,
            "worst_cohort": None,
            "retention_trend": "stable",
            "alerts": [],
            "narrative": "",
        }

    # ── Retention averages ────────────────────────────────────────────────────
    ret30_vals = [c["retention_30d"] for c in cohorts if c["retention_30d"] is not None]
    ret90_vals = [c["retention_90d"] for c in cohorts if c["retention_90d"] is not None]

    avg_ret30 = sum(ret30_vals) / len(ret30_vals) if ret30_vals else 0.0
    avg_ret90 = sum(ret90_vals) / len(ret90_vals) if ret90_vals else 0.0

    # ── LTV ───────────────────────────────────────────────────────────────────
    ltv_vals = [c["ltv_cents"] for c in cohorts if c["ltv_cents"] > 0]
    avg_ltv  = int(sum(ltv_vals) / len(ltv_vals)) if ltv_vals else 0

    # ── CAC: use provided per-cohort CAC if available, else fallback ──────────
    cac_vals = [c["cac_cents"] for c in cohorts if c["cac_cents"] > 0]
    avg_cac  = int(sum(cac_vals) / len(cac_vals)) if cac_vals else overall_cac_cents

    ltv_cac = avg_ltv / avg_cac if avg_cac > 0 else 0.0

    # ── Monthly churn (approx from 30d retention) ─────────────────────────────
    churn_rate = 1.0 - avg_ret30 if avg_ret30 > 0 else 0.0

    # ── Best / worst cohort (by 30d retention, fallback to LTV) ──────────────
    sortable = [c for c in cohorts if c["retention_30d"] is not None]
    best  = max(sortable, key=lambda c: c["retention_30d"]) if sortable else None
    worst = min(sortable, key=lambda c: c["retention_30d"]) if sortable else None

    def _cohort_summary(c: dict[str, Any] | None) -> dict[str, Any] | None:
        if c is None:
            return None
        return {
            "period":        c["period"],
            "users":         c["users"],
            "retention_30d": c["retention_30d"],
            "retention_90d": c["retention_90d"],
            "ltv_cents":     c["ltv_cents"],
        }

    # ── Retention trend: compare first half vs second half ───────────────────
    retention_trend = "stable"
    if len(ret30_vals) >= 4:
        mid = len(ret30_vals) // 2
        first_half_avg  = sum(ret30_vals[:mid]) / mid
        second_half_avg = sum(ret30_vals[mid:]) / (len(ret30_vals) - mid)
        delta = second_half_avg - first_half_avg
        if delta > 0.03:
            retention_trend = "improving"
        elif delta < -0.03:
            retention_trend = "degrading"

    return {
        "cohorts_analyzed": len(cohorts),
        "avg_retention_30d": round(avg_ret30, 4),
        "avg_retention_90d": round(avg_ret90, 4),
        "avg_ltv_cents":     avg_ltv,
        "avg_cac_cents":     avg_cac,
        "ltv_cac_ratio":     round(ltv_cac, 2),
        "churn_rate":        round(churn_rate, 4),
        "best_cohort":       _cohort_summary(best),
        "worst_cohort":      _cohort_summary(worst),
        "retention_trend":   retention_trend,
        "alerts":            [],
        "narrative":         "",
    }


def _build_cohort_alerts(metrics: dict[str, Any]) -> list[dict[str, str]]:
    """Generate actionable alerts from cohort metrics."""
    alerts: list[dict[str, str]] = []

    ltv_cac   = metrics.get("ltv_cac_ratio", 0.0)
    churn     = metrics.get("churn_rate", 0.0)
    ret30     = metrics.get("avg_retention_30d", 0.0)
    trend     = metrics.get("retention_trend", "stable")
    avg_ltv   = metrics.get("avg_ltv_cents", 0)
    avg_cac   = metrics.get("avg_cac_cents", 0)

    # LTV:CAC ratio benchmarks (SaaS: >3.0 good, <1.0 critical)
    if ltv_cac < 1.0 and avg_cac > 0:
        alerts.append({
            "level": "critical",
            "message": (
                f"LTV:CAC ratio is {ltv_cac:.2f}x — spending more to acquire "
                "customers than they generate. Business model unsustainable."
            ),
        })
    elif ltv_cac < 3.0 and avg_cac > 0:
        alerts.append({
            "level": "high",
            "message": (
                f"LTV:CAC ratio {ltv_cac:.2f}x is below 3.0x SaaS benchmark. "
                "Improve retention or reduce CAC to achieve profitability."
            ),
        })

    if churn > 0.10:
        alerts.append({
            "level": "critical",
            "message": (
                f"Monthly churn rate {churn:.0%} is dangerously high. "
                "At this rate, median customer lifetime is less than 10 months."
            ),
        })
    elif churn > 0.05:
        alerts.append({
            "level": "high",
            "message": (
                f"Monthly churn {churn:.0%} exceeds 5% benchmark. "
                "Invest in customer success and onboarding to reduce churn."
            ),
        })

    if ret30 < 0.30 and metrics.get("cohorts_analyzed", 0) > 0:
        alerts.append({
            "level": "high",
            "message": (
                f"30-day retention is only {ret30:.0%}. "
                "Most users are not returning after first month — review onboarding."
            ),
        })

    if trend == "degrading":
        alerts.append({
            "level": "medium",
            "message": (
                "Retention trend is degrading across cohorts. "
                "Recent cohorts retain fewer users than earlier ones."
            ),
        })

    return alerts


# ── LLM Narrative ─────────────────────────────────────────────────────────────

async def _generate_cohort_narrative(metrics: dict[str, Any], settings) -> str:
    """Optional LLM narrative -- falls back to rule-based summary."""
    try:
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import HumanMessage

        llm = ChatOpenAI(
            model=settings.openai_model,
            temperature=0.3,
            max_tokens=300,
            api_key=settings.openai_api_key,
        )
        ltv_cac = metrics["ltv_cac_ratio"]
        churn   = metrics["churn_rate"]
        ret30   = metrics["avg_retention_30d"]
        trend   = metrics["retention_trend"]
        prompt = (
            f"Cohort analysis: LTV:CAC={ltv_cac:.2f}x, monthly_churn={churn:.1%}, "
            f"30d_retention={ret30:.1%}, trend={trend}. "
            "Write a 2-sentence CMO-level insight on customer retention health."
        )
        resp = await llm.ainvoke([HumanMessage(content=prompt)])
        return resp.content.strip()
    except Exception:
        ltv_cac = metrics.get("ltv_cac_ratio", 0.0)
        churn   = metrics.get("churn_rate", 0.0)
        ret30   = metrics.get("avg_retention_30d", 0.0)
        n       = metrics.get("cohorts_analyzed", 0)
        return (
            f"Analyzed {n} cohorts: 30-day retention {ret30:.0%}, "
            f"monthly churn {churn:.0%}, LTV:CAC {ltv_cac:.2f}x."
        )


# ── LangGraph Node ─────────────────────────────────────────────────────────────

async def run_cohort_agent(state: CMOState, config: dict) -> dict[str, Any]:
    """
    CMO Cohort Skill.
    done_when: state['cohorts']['ltv_cac_ratio'] is a float.
    """
    csv_text = state.get("cohort_csv") or ""

    if not csv_text.strip():
        logger.info("CMO CohortAgent: no cohort_csv provided -- skipping")
        return {"cohorts": None}

    try:
        # Pass overall CAC from campaign data if available
        campaign_data = state.get("campaigns") or {}
        overall_cac   = campaign_data.get("overall_cac_cents", 0)

        rows    = _parse_cohort_csv(csv_text)
        metrics = _compute_cohort_metrics(rows, overall_cac_cents=overall_cac)
        alerts  = _build_cohort_alerts(metrics)
        metrics["alerts"] = alerts

        try:
            from app.config import get_settings
            settings = get_settings()
            metrics["narrative"] = await _generate_cohort_narrative(metrics, settings)
        except Exception:
            metrics["narrative"] = ""

        logger.info(
            "CMO CohortAgent: job=%s cohorts=%d ltv_cac=%.2f churn=%.1f%%",
            state.get("job_id"), metrics["cohorts_analyzed"],
            metrics["ltv_cac_ratio"], metrics["churn_rate"] * 100,
        )
        return {"cohorts": metrics}

    except Exception as exc:
        logger.exception("CMO CohortAgent failed for job=%s", state.get("job_id"))
        return {"cohorts": None, "error": f"CohortAgent error: {exc}"}
