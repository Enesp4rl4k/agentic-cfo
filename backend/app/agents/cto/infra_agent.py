"""
Infra Agent — CTO Skill 1 of 5.

Responsibility: Analyze cloud infrastructure costs from billing exports.
Supports: AWS Cost Explorer CSV, GCP Billing CSV, generic format.

Detects:
- Top cost drivers by service
- Environment breakdown (prod / staging / dev)
- Waste: idle resources, over-provisioned services, unused storage
- Month-over-month cost change
- LLM narrative + actionable recommendations

done_when: state['infra']['total_cost_cents'] is an integer.
"""
from __future__ import annotations

import csv
import io
import logging
import re
import statistics
from collections import defaultdict
from typing import Any

from app.agents.cto.state import CTOState, CTORunConfig, CTOSkillResult

logger = logging.getLogger(__name__)

# Environment detection keywords
ENV_KEYWORDS = {
    "prod":    ["prod", "production", "prd", "live"],
    "staging": ["staging", "stage", "stg", "uat", "pre-prod", "preprod"],
    "dev":     ["dev", "development", "sandbox", "test", "qa", "local"],
}

# Services considered high-waste risk if cost > threshold
WASTE_THRESHOLD_CENTS = 5_000_00  # $5,000/month per service triggers review


def _detect_environment(name: str) -> str:
    """Guess environment from service/resource name."""
    name_lower = name.lower()
    for env, keywords in ENV_KEYWORDS.items():
        if any(kw in name_lower for kw in keywords):
            return env
    return "prod"  # conservative default


def _parse_billing_csv(csv_text: str) -> list[dict[str, Any]]:
    """
    Parse cloud billing CSV into normalized rows.
    Handles: AWS Cost Explorer, GCP Billing, generic (service, cost, date columns).

    Returns list of: {service, cost_cents, date, environment, description}
    """
    rows = []
    reader = csv.DictReader(io.StringIO(csv_text.strip()))
    if not reader.fieldnames:
        return rows

    fields_lower = {f.lower(): f for f in (reader.fieldnames or [])}

    # Column name mapping (AWS / GCP / generic)
    def _col(*candidates: str) -> str | None:
        for c in candidates:
            if c.lower() in fields_lower:
                return fields_lower[c.lower()]
        return None

    service_col  = _col("service", "product_name", "productname", "service_name", "Service")
    cost_col     = _col("cost", "amount", "unblended_cost", "totalcost", "Cost")
    date_col     = _col("date", "usage_start_date", "month", "start_date", "Date")
    desc_col     = _col("description", "usage_type", "resource_id", "Description")

    if not service_col or not cost_col:
        logger.warning("InfraAgent: could not detect service/cost columns in CSV")
        return rows

    for row in reader:
        service = (row.get(service_col) or "unknown").strip()
        raw_cost = (row.get(cost_col) or "0").strip().replace("$", "").replace(",", "")
        try:
            cost_cents = int(float(raw_cost) * 100)
        except (ValueError, TypeError):
            continue
        if cost_cents <= 0:
            continue

        date = row.get(date_col, "") if date_col else ""
        desc = row.get(desc_col, "") if desc_col else ""
        environment = _detect_environment(f"{service} {desc}")

        rows.append({
            "service": service,
            "cost_cents": cost_cents,
            "date": str(date)[:7],  # YYYY-MM
            "environment": environment,
            "description": desc,
        })

    return rows


def _compute_infra_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Pure calculation — no LLM."""
    if not rows:
        return {}

    total_cost = sum(r["cost_cents"] for r in rows)

    # By service
    service_totals: dict[str, int] = defaultdict(int)
    for r in rows:
        service_totals[r["service"]] += r["cost_cents"]

    top_services = sorted(service_totals.items(), key=lambda x: x[1], reverse=True)[:10]
    top_cost_drivers = [
        {
            "service": svc,
            "cost_cents": cost,
            "pct": round(cost / total_cost * 100, 1) if total_cost else 0,
        }
        for svc, cost in top_services
    ]

    # By environment
    env_totals: dict[str, int] = defaultdict(int)
    for r in rows:
        env_totals[r["environment"]] += r["cost_cents"]

    # Month-over-month
    monthly: dict[str, int] = defaultdict(int)
    for r in rows:
        if r["date"]:
            monthly[r["date"]] += r["cost_cents"]
    sorted_months = sorted(monthly.keys())
    mom_change_pct: float | None = None
    if len(sorted_months) >= 2:
        prev = monthly[sorted_months[-2]]
        curr = monthly[sorted_months[-1]]
        if prev > 0:
            mom_change_pct = round((curr - prev) / prev * 100, 1)

    # Waste detection: services over threshold with "dev/test" in name
    waste_items = []
    for svc, cost in service_totals.items():
        if cost > WASTE_THRESHOLD_CENTS and _detect_environment(svc) in ("dev", "staging"):
            waste_items.append({
                "service": svc,
                "reason": f"Non-production environment spending ${cost/100:,.0f}/month",
                "savings_cents": int(cost * 0.6),  # assume 60% reducible
            })

    waste_estimate_cents = sum(w["savings_cents"] for w in waste_items)

    return {
        "total_cost_cents": total_cost,
        "by_service": dict(service_totals),
        "by_environment": dict(env_totals),
        "top_cost_drivers": top_cost_drivers,
        "waste_estimate_cents": waste_estimate_cents,
        "waste_items": waste_items,
        "mom_change_pct": mom_change_pct,
        "months_analyzed": len(sorted_months),
    }


def _build_infra_alerts(metrics: dict[str, Any]) -> list[dict[str, str]]:
    alerts = []
    mom = metrics.get("mom_change_pct")
    if mom is not None and mom > 20:
        alerts.append({
            "level": "warning",
            "message": f"Cloud costs increased {mom:.1f}% month-over-month. Review for unexpected usage.",
        })
    if mom is not None and mom > 50:
        alerts[0]["level"] = "critical"  # type: ignore[index]

    waste = metrics.get("waste_estimate_cents", 0)
    if waste > 10_000_00:  # > $10k/month waste
        alerts.append({
            "level": "warning",
            "message": (
                f"Estimated ${waste/100:,.0f}/month cloud waste detected. "
                "Review non-production environment sizing."
            ),
        })

    total = metrics.get("total_cost_cents", 0)
    top_drivers = metrics.get("top_cost_drivers", [])
    if top_drivers and top_drivers[0]["pct"] > 60:
        alerts.append({
            "level": "warning",
            "message": (
                f"Single service '{top_drivers[0]['service']}' accounts for "
                f"{top_drivers[0]['pct']:.0f}% of cloud spend. High concentration risk."
            ),
        })

    return alerts


async def _generate_infra_narrative(
    metrics: dict[str, Any],
    alerts: list[dict[str, str]],
    settings,
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

    top = metrics.get("top_cost_drivers", [])[:5]
    top_text = "\n".join(
        f"  - {d['service']}: ${d['cost_cents']/100:,.0f} ({d['pct']}%)"
        for d in top
    )
    alert_text = (
        "\n".join(f"- [{a['level'].upper()}] {a['message']}" for a in alerts)
        or "No critical alerts."
    )
    waste = metrics.get("waste_estimate_cents", 0)
    mom = metrics.get("mom_change_pct")

    messages = [
        SystemMessage(content=(
            "Sen deneyimli bir CTO ve bulut mimarısın. "
            "Altyapı maliyet verilerini analiz et ve Türkçe olarak kısa, eyleme dönüştürülebilir bir özet yaz. "
            "Yanıt şu yapıda olsun:\n"
            "1. Mevcut bulut harcamasının 1-2 cümlelik değerlendirmesi (MoM değişim ve israf odaklı)\n"
            "2. En kritik maliyet riski veya optimizasyon fırsatı\n"
            "3. Ekibin hemen yapması gereken 2-3 somut maliyet iyileştirmesi (öncelik sırasıyla, TL cinsinden etki belirt)\n"
            "FinOps perspektifinden pratik öneriler ekle."
        )),
        HumanMessage(content=(
            f"Aylık Toplam Bulut Harcaması: {metrics.get('total_cost_cents', 0)/100:,.0f} ₺\n"
            f"Aylık Değişim: {f'{mom:+.1f}%' if mom is not None else 'N/A'}\n"
            f"Tahmini İsraf: {waste/100:,.0f} ₺/ay\n\n"
            f"En Yüksek Maliyetli Servisler:\n{top_text}\n\n"
            f"Uyarılar:\n{alert_text}"
        )),
    ]
    response = await llm.ainvoke(messages)
    return response.content.strip()


async def run_infra_agent(
    state: CTOState,
    config: CTORunConfig,
) -> CTOSkillResult:
    """
    InfraAgent Skill.
    done_when: state['infra']['total_cost_cents'] is an integer.
    """
    billing_csv = state.get("cloud_billing_csv")
    if not billing_csv:
        return CTOSkillResult(
            ok=True,
            patch={"infra": None},
            confidence=1.0,
            detail="No cloud billing data provided — InfraAgent skipped.",
        )

    try:
        from app.config import get_settings
        settings = get_settings()

        rows = _parse_billing_csv(billing_csv)
        if not rows:
            return CTOSkillResult(
                ok=False,
                detail="Could not parse billing CSV — no valid rows found.",
                confidence=0.3,
                needs_review=True,
            )

        metrics = _compute_infra_metrics(rows)
        alerts = _build_infra_alerts(metrics)
        narrative = await _generate_infra_narrative(metrics, alerts, settings)

        metrics["alerts"] = alerts
        metrics["narrative"] = narrative

        has_critical = any(a["level"] == "critical" for a in alerts)
        confidence = 0.92 if not has_critical else 0.80

        logger.info(
            "InfraAgent: job=%s total=$%,.0f waste=$%,.0f alerts=%d",
            state.get("job_id"),
            metrics["total_cost_cents"] / 100,
            metrics["waste_estimate_cents"] / 100,
            len(alerts),
        )

        return CTOSkillResult(
            ok=True,
            patch={"infra": metrics},
            confidence=confidence,
            needs_review=has_critical,
            detail=(
                f"Cloud spend: ${metrics['total_cost_cents']/100:,.0f}, "
                f"waste: ${metrics['waste_estimate_cents']/100:,.0f}, "
                f"alerts: {len(alerts)}"
            ),
        )

    except Exception as exc:
        logger.exception("InfraAgent failed for job=%s", state.get("job_id"))
        return CTOSkillResult(ok=False, detail=f"InfraAgent error: {exc}")
