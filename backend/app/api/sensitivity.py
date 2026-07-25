"""
Sensitivity Analysis API — What-If endpoints.

POST /api/v1/analysis/{job_id}/sensitivity/matrix
    2D sensitivity matrix: two variables × their ranges → net_income grid

POST /api/v1/analysis/{job_id}/sensitivity/variable
    1D sensitivity: single variable → list of outcomes

GET  /api/v1/analysis/{job_id}/sensitivity/variables
    List available variables and their default ranges
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.report import Report, ReportFormat

router = APIRouter()
logger = logging.getLogger(__name__)


class SensitivityMatrixRequest(BaseModel):
    row_variable: str = Field(
        default="headcount_change_pct",
        description="Row axis variable (see GET /variables for options)",
    )
    col_variable: str = Field(
        default="pricing_change_pct",
        description="Column axis variable",
    )
    row_range: list[float] | None = Field(
        default=None,
        description="Custom % values for row axis. If None, uses default range.",
    )
    col_range: list[float] | None = Field(
        default=None,
        description="Custom % values for col axis.",
    )


class SensitivityVariableRequest(BaseModel):
    variable: str = Field(
        default="headcount_change_pct",
        description="Variable to analyze",
    )
    change_range: list[float] | None = Field(
        default=None,
        description="Custom % change values. If None, uses default range.",
    )


async def _get_pnl_for_job(job_id: str, db: AsyncSession) -> dict[str, Any]:
    """Fetch the most recent P&L JSON for a job from the reports table."""
    result = await db.execute(
        select(Report)
        .where(
            Report.job_id == job_id,
            Report.report_format == ReportFormat.JSON,
        )
        .order_by(Report.created_at.desc())
        .limit(1)
    )
    report = result.scalar_one_or_none()
    if not report or not report.data:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No P&L data found for job '{job_id}'. "
                "Run the CFO analysis pipeline first."
            ),
        )
    pnl = report.data.get("pnl")
    if not pnl:
        raise HTTPException(
            status_code=422,
            detail="P&L data is missing from the analysis report.",
        )
    return pnl


@router.get("/analysis/{job_id}/sensitivity/variables")
async def list_sensitivity_variables(job_id: str) -> dict[str, Any]:
    """List all available sensitivity variables and their default ranges."""
    from app.agents.sensitivity_agent import DEFAULT_RANGES, VARIABLE_LABELS
    return {
        "data": {
            "variables": [
                {
                    "key": key,
                    "label": VARIABLE_LABELS.get(key, key),
                    "default_range": rng,
                    "unit": "%",
                }
                for key, rng in DEFAULT_RANGES.items()
            ]
        },
        "error": None,
    }


@router.post("/analysis/{job_id}/sensitivity/matrix")
async def compute_sensitivity_matrix(
    job_id: str,
    body: SensitivityMatrixRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Compute a 2D sensitivity matrix.

    Returns a grid of net_income values showing how the outcome changes
    as two variables vary simultaneously.

    Example: row=headcount (-30% to +30%), col=pricing (-20% to +20%)
    → 7x7 matrix of net_income outcomes + best/worst case analysis.

    The matrix is ready for heatmap rendering on the frontend.
    """
    from app.agents.sensitivity_agent import (
        compute_sensitivity_matrix,
        DEFAULT_RANGES,
        VARIABLE_LABELS,
    )

    # Validate variables
    if body.row_variable not in DEFAULT_RANGES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown row_variable '{body.row_variable}'. Valid: {list(DEFAULT_RANGES)}",
        )
    if body.col_variable not in DEFAULT_RANGES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown col_variable '{body.col_variable}'. Valid: {list(DEFAULT_RANGES)}",
        )
    if body.row_variable == body.col_variable:
        raise HTTPException(
            status_code=400,
            detail="row_variable and col_variable must be different.",
        )

    pnl = await _get_pnl_for_job(job_id, db)

    try:
        result = compute_sensitivity_matrix(
            pnl=pnl,
            row_variable=body.row_variable,
            col_variable=body.col_variable,
            row_range=body.row_range,
            col_range=body.col_range,
        )
    except Exception as exc:
        logger.exception("Sensitivity matrix failed for job=%s", job_id)
        raise HTTPException(status_code=500, detail=f"Sensitivity analysis error: {exc}")

    return {"data": result, "error": None}


@router.post("/analysis/{job_id}/sensitivity/variable")
async def compute_single_sensitivity(
    job_id: str,
    body: SensitivityVariableRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    1D sensitivity analysis for a single variable.

    Shows how net_income changes as one variable changes across its range.
    Also identifies the breakeven threshold (where net_income = 0).

    Example: variable=headcount_change_pct
    → List of outcomes for each headcount change from -30% to +30%
    """
    from app.agents.sensitivity_agent import (
        compute_single_variable_sensitivity,
        DEFAULT_RANGES,
    )

    if body.variable not in DEFAULT_RANGES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown variable '{body.variable}'. Valid: {list(DEFAULT_RANGES)}",
        )

    pnl = await _get_pnl_for_job(job_id, db)

    try:
        result = compute_single_variable_sensitivity(
            pnl=pnl,
            variable=body.variable,
            change_range=body.change_range,
        )
    except Exception as exc:
        logger.exception("Single sensitivity failed for job=%s", job_id)
        raise HTTPException(status_code=500, detail=f"Sensitivity analysis error: {exc}")

    return {"data": result, "error": None}
