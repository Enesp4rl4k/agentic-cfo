"""Frozen metric catalog — stable IDs for the semantic company model."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.semantic.types import MetricUnit


@dataclass(frozen=True)
class MetricDef:
    metric_id: str
    label: str
    unit: MetricUnit
    owner_role: str
    description: str = ""


# Stable IDs — never rename; add new IDs instead.
METRIC_CATALOG: dict[str, MetricDef] = {
    "finance.revenue": MetricDef(
        "finance.revenue", "Revenue", "cents", "cfo", "Period revenue (minor units)"
    ),
    "finance.gross_margin": MetricDef(
        "finance.gross_margin", "Gross margin", "ratio", "cfo"
    ),
    "finance.net_margin": MetricDef(
        "finance.net_margin", "Net margin", "ratio", "cfo"
    ),
    "finance.ebitda": MetricDef(
        "finance.ebitda", "EBITDA", "cents", "cfo"
    ),
    "finance.operating_cashflow": MetricDef(
        "finance.operating_cashflow", "Operating cash flow", "cents", "cfo"
    ),
    "finance.runway_months": MetricDef(
        "finance.runway_months", "Runway (months)", "months", "cfo"
    ),
    "finance.critical_anomalies": MetricDef(
        "finance.critical_anomalies", "Critical anomalies", "count", "cfo"
    ),
    "finance.canonical_inflow": MetricDef(
        "finance.canonical_inflow", "Canonical inflow", "cents", "cfo",
        "Sum of income-direction canonical transactions",
    ),
    "finance.canonical_outflow": MetricDef(
        "finance.canonical_outflow", "Canonical outflow", "cents", "cfo",
        "Sum of expense-direction canonical transactions",
    ),
    "finance.canonical_quality_score": MetricDef(
        "finance.canonical_quality_score", "Data quality score", "score", "cfo"
    ),
    "growth.overall_roas": MetricDef(
        "growth.overall_roas", "Overall ROAS", "ratio", "cmo"
    ),
    "growth.blended_cac": MetricDef(
        "growth.blended_cac", "Blended CAC", "cents", "cmo"
    ),
    "growth.conversions": MetricDef(
        "growth.conversions", "Conversions", "count", "cmo"
    ),
    "tech.health_score": MetricDef(
        "tech.health_score", "CTO health score", "score", "cto"
    ),
    "tech.velocity_trend": MetricDef(
        "tech.velocity_trend", "Velocity trend", "string", "cto"
    ),
    "tech.debt_score": MetricDef(
        "tech.debt_score", "Tech debt score", "score", "cto"
    ),
    "tech.infra_waste_pct": MetricDef(
        "tech.infra_waste_pct", "Infra waste %", "percent", "cto"
    ),
    "people.headcount": MetricDef(
        "people.headcount", "Headcount", "count", "chro"
    ),
    "people.attrition_rate": MetricDef(
        "people.attrition_rate", "Attrition rate", "ratio", "chro"
    ),
    "people.turnover_rate": MetricDef(
        "people.turnover_rate", "Turnover rate", "ratio", "chro"
    ),
    "ops.bottleneck_count": MetricDef(
        "ops.bottleneck_count", "Bottleneck count", "count", "coo"
    ),
    "ops.sla_breach_rate": MetricDef(
        "ops.sla_breach_rate", "SLA breach rate", "ratio", "coo"
    ),
    "risk.overall_score": MetricDef(
        "risk.overall_score", "Risk score", "score", "risk"
    ),
    "risk.critical_kri_count": MetricDef(
        "risk.critical_kri_count", "Critical KRIs", "count", "risk"
    ),
}


def catalog_list() -> list[dict[str, Any]]:
    return [
        {
            "metric_id": m.metric_id,
            "label": m.label,
            "unit": m.unit,
            "owner_role": m.owner_role,
            "description": m.description,
        }
        for m in METRIC_CATALOG.values()
    ]


def is_known_metric(metric_id: str) -> bool:
    return metric_id in METRIC_CATALOG


# Metrics used for health score weighting (higher weight = more important)
HEALTH_WEIGHTS: dict[str, float] = {
    "finance.runway_months": 0.25,
    "finance.net_margin": 0.15,
    "finance.critical_anomalies": 0.15,
    "growth.overall_roas": 0.10,
    "tech.health_score": 0.10,
    "people.attrition_rate": 0.10,
    "risk.overall_score": 0.15,
}
