"""
Report Agent — Skill 5 of 5.

Responsibility: Generate Excel report and dashboard JSON from P&L, Cash Flow,
and Forecast results.

done_when: state['report_paths']['xlsx'] exists on disk AND state['dashboard_json'] is populated.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

from app.agents.state import CFOState, AgentRunConfig, SkillResult
from app.config import get_settings

logger = logging.getLogger(__name__)


def _fmt(cents: int) -> str:
    return cents / 100


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
        "generated_at": datetime.now(timezone.utc).isoformat(),
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
        "alerts": all_alerts,
        "recent_transactions": recent_transactions,
        "transaction_count": len(transactions),
    }


def _write_excel(
    pnl: dict[str, Any],
    cashflow: dict[str, Any],
    forecast: dict[str, Any],
    output_path: str,
) -> None:
    """Write a multi-sheet Excel report using openpyxl."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, numbers
    from openpyxl.utils import get_column_letter

    HEADER_FILL = PatternFill("solid", fgColor="1E3A5F")
    HEADER_FONT = Font(color="FFFFFF", bold=True)
    SUBHEADER_FILL = PatternFill("solid", fgColor="E8F0FE")
    CURRENCY_FORMAT = '#,##0.00'

    wb = Workbook()

    # ── Sheet 1: P&L ──────────────────────────────────────────────────────────
    ws_pnl = wb.active
    ws_pnl.title = "P&L Statement"

    pnl_rows = [
        ("Revenue", pnl.get("revenue", 0)),
        ("Cost of Goods Sold (COGS)", -pnl.get("cogs", 0)),
        ("Gross Profit", pnl.get("gross_profit", 0)),
        ("Gross Margin %", pnl.get("gross_margin", 0) * 100),
        ("", None),
        ("Operating Expenses", None),
        *[(f"  {k.replace('_', ' ').title()}", -v) for k, v in pnl.get("opex", {}).items()],
        ("Total OpEx", -pnl.get("total_opex", 0)),
        ("", None),
        ("EBITDA", pnl.get("ebitda", 0)),
        ("EBITDA Margin %", pnl.get("ebitda_margin", 0) * 100),
        ("Tax", -pnl.get("tax", 0)),
        ("Loan Payments", -pnl.get("loan_payments", 0)),
        ("Net Income", pnl.get("net_income", 0)),
        ("Net Margin %", pnl.get("net_margin", 0) * 100),
    ]

    ws_pnl.append(["Item", "Amount ($)"])
    for cell in ws_pnl[1]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT

    for label, value in pnl_rows:
        if value is None:
            ws_pnl.append([label, ""])
        elif "%" in label:
            ws_pnl.append([label, round(value, 2)])
        else:
            ws_pnl.append([label, _fmt(int(value)) if isinstance(value, (int, float)) else value])

    ws_pnl.column_dimensions["A"].width = 35
    ws_pnl.column_dimensions["B"].width = 18

    if pnl.get("narrative"):
        ws_pnl.append([])
        ws_pnl.append(["CFO Commentary"])
        ws_pnl[-1][0].font = Font(bold=True)
        ws_pnl.append([pnl["narrative"]])
        ws_pnl[ws_pnl.max_row][0].alignment = Alignment(wrap_text=True)
        ws_pnl.row_dimensions[ws_pnl.max_row].height = 80

    # ── Sheet 2: Cash Flow ────────────────────────────────────────────────────
    ws_cf = wb.create_sheet("Cash Flow")
    ws_cf.append(["Activity", "Amount ($)"])
    for cell in ws_cf[1]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT

    cf_rows = [
        ("Operating Cash Flow", cashflow.get("operating", 0)),
        ("  Cash Inflows", cashflow.get("operating_in", 0)),
        ("  Cash Outflows", -cashflow.get("operating_out", 0)),
        ("Investing Cash Flow", cashflow.get("investing", 0)),
        ("Financing Cash Flow", cashflow.get("financing", 0)),
        ("Net Cash Change", cashflow.get("net_change", 0)),
    ]
    for label, value in cf_rows:
        ws_cf.append([label, _fmt(int(value))])

    ws_cf.append([])
    ws_cf.append(["Monthly Cash Flow"])
    ws_cf[-1][0].font = Font(bold=True)
    ws_cf.append(["Month", "Cash In ($)", "Cash Out ($)", "Net ($)"])
    for cell in ws_cf[ws_cf.max_row]:
        cell.fill = SUBHEADER_FILL

    for entry in cashflow.get("monthly_series", []):
        ws_cf.append([
            entry["month"],
            _fmt(entry["in"]),
            _fmt(entry["out"]),
            _fmt(entry["net"]),
        ])

    ws_cf.column_dimensions["A"].width = 30
    for col in ["B", "C", "D"]:
        ws_cf.column_dimensions[col].width = 16

    # ── Sheet 3: Forecast ─────────────────────────────────────────────────────
    ws_fc = wb.create_sheet("Forecast")
    ws_fc.append(["12-Month Financial Forecast"])
    ws_fc[1][0].font = Font(bold=True, size=13)
    ws_fc.append([])

    for scenario_key, scenario in forecast.get("scenarios", {}).items():
        ws_fc.append([scenario["label"], scenario.get("description", "")])
        ws_fc[-1][0].font = Font(bold=True)
        ws_fc.append(["Month", "Cash In ($)", "Cash Out ($)", "Net ($)"])
        for cell in ws_fc[ws_fc.max_row]:
            cell.fill = HEADER_FILL
            cell.font = HEADER_FONT
        for entry in scenario.get("months", []):
            ws_fc.append([
                entry["month"],
                _fmt(entry["in"]),
                _fmt(entry["out"]),
                _fmt(entry["net"]),
            ])
        ws_fc.append([
            "12-Month Net",
            "",
            "",
            _fmt(scenario.get("twelve_month_net", 0)),
        ])
        ws_fc.append([
            "Cash Runway",
            f"{scenario.get('runway_months', 'Stable')} months",
            "",
            "",
        ])
        ws_fc.append([])

    ws_fc.column_dimensions["A"].width = 20
    for col in ["B", "C", "D"]:
        ws_fc.column_dimensions[col].width = 16

    wb.save(output_path)


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
