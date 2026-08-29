"""
Report Agent — Skill 5 of 5.

Responsibility: Orchestrates generation of multi-sheet Excel reports and
normalized dashboard JSON payloads.

SOLID Refactoring:
- Single Responsibility: Excel rendering delegated to ExcelReportExporter.
- Open/Closed: Exporters implement IReportExporter.
- Interface Segregation: Uses granular report exporter interfaces.

done_when: state['report_paths']['xlsx'] exists on disk AND state['dashboard_json'] is populated.
"""
from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import Any

from app.agents.state import AgentRunConfig, CFOState, SkillResult
from app.config import get_settings
from app.core.container import get_report_exporter

logger = logging.getLogger(__name__)


def _fmt(cents: float) -> float | str:
    """Format cents to major currency float (or string in exporter)."""
    return cents / 100 if isinstance(cents, (int, float)) else cents


def _build_dashboard_json(state: CFOState) -> dict[str, Any]:
    """Build the JSON payload consumed by the frontend dashboard."""
    pnl = state.get("pnl", {})
    cashflow = state.get("cashflow", {})
    forecast = state.get("forecast", {})
    transactions = state.get("transactions", [])

    # KPI cards
    kpis = [
        {
            "label": "Revenue",
            "value": _fmt(pnl.get("revenue", 0)),
            "format": "currency",
            "trend": None,
        },
        {
            "label": "Net Income",
            "value": _fmt(pnl.get("net_income", 0)),
            "format": "currency",
            "trend": None,
        },
        {
            "label": "Gross Margin",
            "value": round(pnl.get("gross_margin", 0) * 100, 1),
            "format": "percent",
            "trend": None,
        },
        {
            "label": "Net Cash Flow",
            "value": _fmt(cashflow.get("net_change", 0)),
            "format": "currency",
            "trend": None,
        },
    ]

    # Add runway KPI if forecast available
    base_scenario = forecast.get("scenarios", {}).get("base", {})
    if base_scenario.get("runway_months") is not None:
        kpis.append({
            "label": "Cash Runway",
            "value": base_scenario["runway_months"],
            "format": "months",
            "trend": None,
        })

    # Add anomaly summary KPI if anomalies detected
    anomalies = state.get("anomalies") or []
    critical_count = sum(1 for a in anomalies if a.get("severity") == "critical")
    high_count = sum(1 for a in anomalies if a.get("severity") == "high")
    if anomalies:
        kpis.append({
            "label": "Anomalies",
            "value": len(anomalies),
            "format": "count",
            "trend": None,
            "critical": critical_count,
            "high": high_count,
        })

    # Recent transactions (last 20)
    recent_transactions = sorted(
        transactions,
        key=lambda t: t.get("transaction_date") or "",
        reverse=True,
    )[:20]

    # All alerts combined
    all_alerts = (
        cashflow.get("alerts", []) + forecast.get("alerts", [])
    )

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "kpis": kpis,
        "pnl": {
            "revenue": _fmt(pnl.get("revenue", 0)),
            "cogs": _fmt(pnl.get("cogs", 0)),
            "gross_profit": _fmt(pnl.get("gross_profit", 0)),
            "gross_margin": pnl.get("gross_margin", 0),
            "ebitda": _fmt(pnl.get("ebitda", 0)),
            "ebitda_margin": pnl.get("ebitda_margin", 0),
            "net_income": _fmt(pnl.get("net_income", 0)),
            "net_margin": pnl.get("net_margin", 0),
            "opex": {k: _fmt(v) for k, v in pnl.get("opex", {}).items()},
            "narrative": pnl.get("narrative", ""),
        },
        "cashflow": {
            "operating": _fmt(cashflow.get("operating", 0)),
            "investing": _fmt(cashflow.get("investing", 0)),
            "financing": _fmt(cashflow.get("financing", 0)),
            "net_change": _fmt(cashflow.get("net_change", 0)),
            "monthly_series": cashflow.get("monthly_series", []),
            "narrative": cashflow.get("narrative", ""),
            "alerts": cashflow.get("alerts", []),
        },
        "forecast": {
            "scenarios": {
                k: {
                    "label": v.get("label"),
                    "description": v.get("description"),
                    "runway_months": v.get("runway_months"),
                    "twelve_month_net": _fmt(v.get("twelve_month_net", 0)),
                    "months": v.get("months", []),
                }
                for k, v in forecast.get("scenarios", {}).items()
            },
            "narrative": forecast.get("narrative", ""),
        },
        "anomalies": state.get("anomalies", []),
        "anomaly_narrative": state.get("anomaly_narrative", ""),
        "triggered_alerts": state.get("triggered_alerts", []),

        # Budget agent
        "budget": state.get("budget"),

        # Tax agent
        "tax": (
            {
                "vat_payable": state["tax"]["vat"]["net_vat_payable"],
                "withholding_tax": state["tax"]["withholding"]["income_tax_withholding"],
                "corporate_tax_estimate": state["tax"]["corporate"]["corporate_tax_estimate"],
                "total_tax_burden": state["tax"]["total_tax_burden"],
                "payment_calendar": state["tax"]["payment_calendar"],
                "narrative": state["tax"].get("narrative", ""),
            }
            if state.get("tax") else None
        ),

        # Multi-period agent
        "multi_period": state.get("multi_period"),

        "alerts": all_alerts,
        "recent_transactions": recent_transactions,
        "transaction_count": len(transactions),

        # Confidence decomposition — why min_confidence is what it is
        "min_confidence": state.get("min_confidence"),
        "confidence_breakdown": state.get("confidence_breakdown"),
        "verifier_verdict": state.get("verifier_verdict"),
    }


def _write_excel(
    pnl: dict[str, Any],
    cashflow: dict[str, Any],
    forecast: dict[str, Any],
    output_path: str,
) -> str:
    """Delegates to ExcelReportExporter resolved from DI container."""
    exporter = get_report_exporter()
    return exporter.export(pnl, cashflow, forecast, output_path)


async def run_report(state: CFOState, config: AgentRunConfig) -> SkillResult:
    """
    Report Skill.
    done_when: state['report_paths']['xlsx'] exists AND state['dashboard_json'] is populated.
    """
    pnl = state.get("pnl", {})
    cashflow = state.get("cashflow", {})
    forecast = state.get("forecast", {})

    if not pnl or not cashflow:
        return SkillResult(
            ok=False,
            detail="P&L or cash flow data missing — cannot generate report.",
            halt=True,
        )

    try:
        settings = get_settings()
        job_id = state.get("job_id", "unknown")

        # Ensure output directory exists
        output_dir = os.path.join(settings.storage_local_path, "reports", job_id)
        os.makedirs(output_dir, exist_ok=True)

        xlsx_path = os.path.join(output_dir, "financial_report.xlsx")
        _write_excel(pnl, cashflow, forecast, xlsx_path)

        dashboard_json = _build_dashboard_json(state)

        return SkillResult(
            ok=True,
            patch={
                "report_paths": {"xlsx": xlsx_path},
                "dashboard_json": dashboard_json,
            },
            confidence=1.0,
            detail=f"Report generated: {xlsx_path}",
        )
    except Exception as exc:
        logger.exception("Report agent failed for job=%s", state.get("job_id"))
        return SkillResult(ok=False, detail=f"Report error: {exc}")
