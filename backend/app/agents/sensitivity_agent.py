"""
Sensitivity Analysis Agent — What-If Analysis Engine.

Computes a 2D sensitivity matrix showing how net income changes
when two variables change simultaneously.

Supported variables:
  - headcount_change_pct  : % change in salary/headcount costs (-30 to +30)
  - pricing_change_pct    : % change in revenue (-20 to +20)
  - growth_rate_change_pct: % change in growth assumptions (-15 to +15)
  - cogs_change_pct       : % change in COGS (-20 to +20)
  - opex_change_pct       : % change in operating expenses (-30 to +30)

Output: 2D matrix of net_income outcomes + heatmap-ready data.

Used by: POST /api/v1/analysis/{job_id}/sensitivity
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# Default axis ranges (percent change)
DEFAULT_RANGES: dict[str, list[float]] = {
    "headcount_change_pct":   [-30, -20, -10, 0, 10, 20, 30],
    "pricing_change_pct":     [-20, -10,  -5, 0,  5, 10, 20],
    "growth_rate_change_pct": [-15, -10,  -5, 0,  5, 10, 15],
    "cogs_change_pct":        [-20, -10,  -5, 0,  5, 10, 20],
    "opex_change_pct":        [-30, -20, -10, 0, 10, 20, 30],
}

VARIABLE_LABELS: dict[str, str] = {
    "headcount_change_pct":   "Personel Değişimi (%)",
    "pricing_change_pct":     "Fiyat Değişimi (%)",
    "growth_rate_change_pct": "Büyüme Hızı Değişimi (%)",
    "cogs_change_pct":        "SMM Değişimi (%)",
    "opex_change_pct":        "Faaliyet Gideri Değişimi (%)",
}


def _apply_variable(
    pnl: dict[str, Any],
    variable: str,
    change_pct: float,
) -> dict[str, Any]:
    """
    Apply a single variable change to a P&L snapshot.
    Returns a modified P&L dict (does not mutate the original).
    """
    p = dict(pnl)
    factor = 1 + change_pct / 100

    if variable == "headcount_change_pct":
        # Salary is the main headcount cost
        salary = p.get("opex", {}).get("salary", 0)
        delta = int(salary * (factor - 1))
        opex = dict(p.get("opex", {}))
        opex["salary"] = int(salary * factor)
        p["opex"] = opex
        p["total_opex"] = p.get("total_opex", 0) + delta

    elif variable == "pricing_change_pct":
        # Revenue changes proportionally
        p["revenue"] = int(p.get("revenue", 0) * factor)

    elif variable == "growth_rate_change_pct":
        # Apply to revenue only (growth rate affects top line)
        p["revenue"] = int(p.get("revenue", 0) * factor)

    elif variable == "cogs_change_pct":
        old_cogs = p.get("cogs", 0)
        p["cogs"] = int(old_cogs * factor)

    elif variable == "opex_change_pct":
        p["total_opex"] = int(p.get("total_opex", 0) * factor)

    # Recompute derived metrics
    p["gross_profit"] = p.get("revenue", 0) - p.get("cogs", 0)
    p["ebitda"]       = p["gross_profit"] - p.get("total_opex", 0)
    p["net_income"]   = p["ebitda"] - p.get("tax", 0) - p.get("loan_payments", 0)

    if p.get("revenue", 0) > 0:
        p["gross_margin"] = round(p["gross_profit"] / p["revenue"], 4)
        p["ebitda_margin"] = round(p["ebitda"] / p["revenue"], 4)
        p["net_margin"]    = round(p["net_income"] / p["revenue"], 4)

    return p


def compute_sensitivity_matrix(
    pnl: dict[str, Any],
    row_variable: str,
    col_variable: str,
    row_range: list[float] | None = None,
    col_range: list[float] | None = None,
) -> dict[str, Any]:
    """
    Compute a 2D sensitivity matrix.

    Args:
        pnl:          Base P&L dict (from pnl_agent output)
        row_variable: First variable to change (rows)
        col_variable: Second variable to change (columns)
        row_range:    List of % values to test for row variable
        col_range:    List of % values to test for col variable

    Returns:
        {
          "row_variable": "headcount_change_pct",
          "col_variable": "pricing_change_pct",
          "row_values": [-30, -20, ...],
          "col_values": [-20, -10, ...],
          "matrix": [[net_income_cents, ...], ...],  # [row][col]
          "matrix_margin": [[net_margin_pct, ...], ...],
          "base_net_income": int,
          "best_case": {"row": float, "col": float, "net_income": int},
          "worst_case": {"row": float, "col": float, "net_income": int},
        }
    """
    row_values = row_range or DEFAULT_RANGES.get(row_variable, [0])
    col_values = col_range or DEFAULT_RANGES.get(col_variable, [0])

    base_net = pnl.get("net_income", 0)
    matrix: list[list[int]] = []
    matrix_margin: list[list[float]] = []

    best_val, best_row, best_col = float("-inf"), 0.0, 0.0
    worst_val, worst_row, worst_col = float("inf"), 0.0, 0.0

    for r_pct in row_values:
        row_net: list[int] = []
        row_margin: list[float] = []
        for c_pct in col_values:
            # Apply row variable first, then col variable
            modified = _apply_variable(pnl, row_variable, r_pct)
            modified = _apply_variable(modified, col_variable, c_pct)
            net = modified["net_income"]
            margin_pct = round(modified.get("net_margin", 0) * 100, 2)
            row_net.append(net)
            row_margin.append(margin_pct)

            if net > best_val:
                best_val, best_row, best_col = net, r_pct, c_pct
            if net < worst_val:
                worst_val, worst_row, worst_col = net, r_pct, c_pct

        matrix.append(row_net)
        matrix_margin.append(row_margin)

    return {
        "row_variable": row_variable,
        "col_variable": col_variable,
        "row_label": VARIABLE_LABELS.get(row_variable, row_variable),
        "col_label": VARIABLE_LABELS.get(col_variable, col_variable),
        "row_values": row_values,
        "col_values": col_values,
        "matrix": matrix,
        "matrix_margin": matrix_margin,
        "base_net_income": base_net,
        "best_case": {
            "row_pct": best_row,
            "col_pct": best_col,
            "net_income": int(best_val),
            "label": (
                f"{VARIABLE_LABELS.get(row_variable, row_variable)} {best_row:+.0f}%, "
                f"{VARIABLE_LABELS.get(col_variable, col_variable)} {best_col:+.0f}%"
            ),
        },
        "worst_case": {
            "row_pct": worst_row,
            "col_pct": worst_col,
            "net_income": int(worst_val),
            "label": (
                f"{VARIABLE_LABELS.get(row_variable, row_variable)} {worst_row:+.0f}%, "
                f"{VARIABLE_LABELS.get(col_variable, col_variable)} {worst_col:+.0f}%"
            ),
        },
    }


def compute_single_variable_sensitivity(
    pnl: dict[str, Any],
    variable: str,
    change_range: list[float] | None = None,
) -> dict[str, Any]:
    """
    1D sensitivity: how does net_income change as one variable changes?
    Returns a list of {pct_change, net_income, delta_vs_base, delta_pct}.
    """
    values = change_range or DEFAULT_RANGES.get(variable, list(range(-20, 25, 5)))
    base_net = pnl.get("net_income", 0)
    results: list[dict[str, Any]] = []

    for pct in values:
        modified = _apply_variable(pnl, variable, pct)
        net = modified["net_income"]
        delta = net - base_net
        delta_pct = round((delta / abs(base_net)) * 100, 1) if base_net != 0 else 0.0
        results.append({
            "pct_change": pct,
            "net_income": net,
            "delta_vs_base": delta,
            "delta_pct": delta_pct,
            "net_margin_pct": round(modified.get("net_margin", 0) * 100, 2),
            "breakeven": net >= 0,
        })

    return {
        "variable": variable,
        "label": VARIABLE_LABELS.get(variable, variable),
        "base_net_income": base_net,
        "results": results,
        "breakeven_threshold": next(
            (r["pct_change"] for r in results if r["breakeven"]), None
        ),
    }
