"""
Alert Agent — Skill 10.

Sorumluluk: Tüm agent çıktılarını tarayıp eşik bazlı uyarılar üretir.
Pipeline'ın son analiz adımıdır — tüm veriler mevcut olduğunda çalışır.

Uyarı kategorileri:
1. Likidite uyarıları (nakit yetersizliği)
2. Karlılık uyarıları (margin düşüşü)
3. Büyüme uyarıları (gelir düşüşü)
4. Vergi uyarıları (yaklaşan ödeme)
5. Bütçe uyarıları (aşım)
6. Anomali uyarıları (kritik anomaliler)
7. Runway uyarıları (nakit bitme tarihi)

done_when: state['triggered_alerts'] is a list (may be empty)
"""
from __future__ import annotations

import logging
from typing import Any

from app.agents.state import CFOState, AgentRunConfig, SkillResult

logger = logging.getLogger(__name__)

# ── Alert thresholds ──────────────────────────────────────────────────────────

THRESHOLDS = {
    "gross_margin_critical": 0.10,    # <10% gross margin
    "gross_margin_warning": 0.20,     # <20% gross margin
    "net_margin_critical": -0.05,     # negative net margin >5%
    "net_margin_warning": 0.02,       # <2% net margin
    "cashflow_runway_critical": 2,    # <2 months runway
    "cashflow_runway_warning": 6,     # <6 months runway
    "revenue_mom_decline_critical": -0.20,  # -20% MoM
    "revenue_mom_decline_warning": -0.10,   # -10% MoM
    "budget_variance_warning": 15.0,  # >15% over budget
    "budget_variance_critical": 30.0, # >30% over budget
    "tax_payment_days_warning": 14,   # payment due within 14 days
}


# ── Alert builders ────────────────────────────────────────────────────────────

def _check_profitability(pnl: dict[str, Any]) -> list[dict[str, Any]]:
    alerts = []
    gross_margin = pnl.get("gross_margin", 1.0)
    net_margin = pnl.get("net_margin", 1.0)
    net_income = pnl.get("net_income", 0)

    if gross_margin < THRESHOLDS["gross_margin_critical"]:
        alerts.append({
            "type": "profitability",
            "severity": "critical",
            "message": (
                f"Gross margin is critically low at {gross_margin*100:.1f}%. "
                f"Cost of goods is consuming most revenue."
            ),
            "threshold": THRESHOLDS["gross_margin_critical"] * 100,
            "actual_value": round(gross_margin * 100, 1),
            "metric": "gross_margin_pct",
        })
    elif gross_margin < THRESHOLDS["gross_margin_warning"]:
        alerts.append({
            "type": "profitability",
            "severity": "warning",
            "message": f"Gross margin is below 20% ({gross_margin*100:.1f}%). Review pricing strategy.",
            "threshold": THRESHOLDS["gross_margin_warning"] * 100,
            "actual_value": round(gross_margin * 100, 1),
            "metric": "gross_margin_pct",
        })

    if net_margin < THRESHOLDS["net_margin_critical"]:
        alerts.append({
            "type": "profitability",
            "severity": "critical",
            "message": (
                f"Business is operating at a significant loss — net margin {net_margin*100:.1f}%. "
                f"Immediate cost reduction or revenue action required."
            ),
            "threshold": THRESHOLDS["net_margin_critical"] * 100,
            "actual_value": round(net_margin * 100, 1),
            "metric": "net_margin_pct",
        })
    elif net_margin < THRESHOLDS["net_margin_warning"] and net_income < 0:
        alerts.append({
            "type": "profitability",
            "severity": "warning",
            "message": f"Net margin is negative ({net_margin*100:.1f}%). Monitor closely.",
            "threshold": THRESHOLDS["net_margin_warning"] * 100,
            "actual_value": round(net_margin * 100, 1),
            "metric": "net_margin_pct",
        })

    return alerts


def _check_cashflow(cashflow: dict[str, Any], forecast: dict[str, Any]) -> list[dict[str, Any]]:
    alerts = []

    if cashflow.get("operating", 0) < 0:
        alerts.append({
            "type": "liquidity",
            "severity": "critical",
            "message": "Operating cash flow is negative — business cannot self-fund operations.",
            "threshold": 0,
            "actual_value": cashflow.get("operating", 0) / 100,
            "metric": "operating_cashflow",
        })

    # Runway from base scenario
    base = forecast.get("scenarios", {}).get("base", {})
    runway = base.get("runway_months")
    if runway is not None:
        if runway <= THRESHOLDS["cashflow_runway_critical"]:
            alerts.append({
                "type": "liquidity",
                "severity": "critical",
                "message": (
                    f"Cash runway is only {runway} month(s) under base scenario. "
                    f"Immediate financing or cost action required."
                ),
                "threshold": THRESHOLDS["cashflow_runway_critical"],
                "actual_value": runway,
                "metric": "runway_months",
            })
        elif runway <= THRESHOLDS["cashflow_runway_warning"]:
            alerts.append({
                "type": "liquidity",
                "severity": "warning",
                "message": (
                    f"Cash runway is {runway} months. "
                    f"Consider arranging credit facility or reducing burn."
                ),
                "threshold": THRESHOLDS["cashflow_runway_warning"],
                "actual_value": runway,
                "metric": "runway_months",
            })

    return alerts


def _check_growth(multi_period: dict[str, Any] | None) -> list[dict[str, Any]]:
    alerts = []
    if not multi_period or not multi_period.get("mom"):
        return alerts

    mom = multi_period["mom"]
    rev_change = mom.get("revenue_change_pct")
    if rev_change is None:
        return alerts

    if rev_change <= THRESHOLDS["revenue_mom_decline_critical"] * 100:
        alerts.append({
            "type": "growth",
            "severity": "critical",
            "message": (
                f"Revenue declined {abs(rev_change):.1f}% month-over-month. "
                f"Investigate customer churn and pipeline."
            ),
            "threshold": THRESHOLDS["revenue_mom_decline_critical"] * 100,
            "actual_value": rev_change,
            "metric": "revenue_mom_pct",
        })
    elif rev_change <= THRESHOLDS["revenue_mom_decline_warning"] * 100:
        alerts.append({
            "type": "growth",
            "severity": "warning",
            "message": f"Revenue declined {abs(rev_change):.1f}% month-over-month.",
            "threshold": THRESHOLDS["revenue_mom_decline_warning"] * 100,
            "actual_value": rev_change,
            "metric": "revenue_mom_pct",
        })

    # Declining trend
    if multi_period.get("trend_direction") == "declining":
        alerts.append({
            "type": "growth",
            "severity": "warning",
            "message": "3-month net cash flow trend is declining. Review business trajectory.",
            "threshold": None,
            "actual_value": None,
            "metric": "net_trend",
        })

    return alerts


def _check_budget(budget: dict[str, Any] | None) -> list[dict[str, Any]]:
    alerts = []
    if not budget:
        return alerts

    total_var_pct = budget.get("total_variance_pct", 0)

    if total_var_pct >= THRESHOLDS["budget_variance_critical"]:
        alerts.append({
            "type": "budget",
            "severity": "critical",
            "message": (
                f"Total expenses are {total_var_pct:.1f}% over budget. "
                f"Immediate budget review required."
            ),
            "threshold": THRESHOLDS["budget_variance_critical"],
            "actual_value": total_var_pct,
            "metric": "total_budget_variance_pct",
        })
    elif total_var_pct >= THRESHOLDS["budget_variance_warning"]:
        alerts.append({
            "type": "budget",
            "severity": "warning",
            "message": f"Expenses are {total_var_pct:.1f}% over budget. Monitor closely.",
            "threshold": THRESHOLDS["budget_variance_warning"],
            "actual_value": total_var_pct,
            "metric": "total_budget_variance_pct",
        })

    # Category-level alerts for biggest overruns
    for item in budget.get("items", []):
        if item.get("variance_pct", 0) >= THRESHOLDS["budget_variance_critical"]:
            alerts.append({
                "type": "budget",
                "severity": "warning",
                "message": (
                    f"{item['category'].replace('_', ' ').title()} is "
                    f"{item['variance_pct']:.1f}% over budget."
                ),
                "threshold": THRESHOLDS["budget_variance_critical"],
                "actual_value": item["variance_pct"],
                "metric": f"budget_{item['category']}_pct",
            })

    return alerts


def _check_tax(tax: dict[str, Any] | None) -> list[dict[str, Any]]:
    alerts = []
    if not tax:
        return alerts

    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).date()

    for payment in tax.get("payment_calendar", []):
        try:
            due = datetime.strptime(payment["due_date"], "%Y-%m-%d").date()
            days_until = (due - today).days
            amount = payment.get("amount", 0)

            if 0 <= days_until <= THRESHOLDS["tax_payment_days_warning"]:
                severity = "critical" if days_until <= 3 else "warning"
                alerts.append({
                    "type": "tax",
                    "severity": severity,
                    "message": (
                        f"{payment['type']} payment of {amount/100:,.0f} due "
                        f"in {days_until} day(s) ({payment['due_date']})."
                    ),
                    "threshold": THRESHOLDS["tax_payment_days_warning"],
                    "actual_value": days_until,
                    "metric": "tax_days_until_due",
                })
        except (ValueError, KeyError):
            continue

    return alerts


def _check_anomalies(anomalies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    alerts = []
    critical = [a for a in anomalies if a.get("severity") == "critical"]
    if critical:
        alerts.append({
            "type": "anomaly",
            "severity": "critical",
            "message": (
                f"{len(critical)} critical financial anomalies detected. "
                f"Review immediately: {', '.join(a['title'] for a in critical[:3])}."
            ),
            "threshold": 0,
            "actual_value": len(critical),
            "metric": "critical_anomaly_count",
        })
    return alerts


# ── Entry point ───────────────────────────────────────────────────────────────

async def run_alerts(
    state: CFOState,
    config: AgentRunConfig,
) -> SkillResult:
    """
    Alert Skill.
    done_when: state['triggered_alerts'] is a list.
    """
    try:
        pnl = state.get("pnl") or {}
        cashflow = state.get("cashflow") or {}
        forecast = state.get("forecast") or {}
        budget = state.get("budget")
        tax = state.get("tax")
        multi_period = state.get("multi_period")
        anomalies = state.get("anomalies") or []

        all_alerts: list[dict[str, Any]] = []
        all_alerts.extend(_check_profitability(pnl))
        all_alerts.extend(_check_cashflow(cashflow, forecast))
        all_alerts.extend(_check_growth(multi_period))
        all_alerts.extend(_check_budget(budget))
        all_alerts.extend(_check_tax(tax))
        all_alerts.extend(_check_anomalies(anomalies))

        # Sort: critical first
        severity_order = {"critical": 0, "warning": 1, "info": 2}
        all_alerts.sort(key=lambda a: severity_order.get(a.get("severity", "info"), 2))

        critical_count = sum(1 for a in all_alerts if a.get("severity") == "critical")
        warning_count = sum(1 for a in all_alerts if a.get("severity") == "warning")

        logger.info(
            "Alert agent: job=%s total=%d critical=%d warning=%d",
            state.get("job_id"), len(all_alerts), critical_count, warning_count,
        )

        return SkillResult(
            ok=True,
            patch={"triggered_alerts": all_alerts},
            confidence=1.0,
            detail=(
                f"Alerts: {len(all_alerts)} total "
                f"({critical_count} critical, {warning_count} warning)"
            ),
        )

    except Exception as exc:
        logger.exception("Alert agent failed for job=%s", state.get("job_id"))
        return SkillResult(ok=False, detail=f"Alert error: {exc}")
