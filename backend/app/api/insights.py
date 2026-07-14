from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.report import Report, ReportFormat
from app.models.analysis_job import AnalysisJob
from app.agents.i18n import SUPPORTED_LANGUAGES, LANG_NAMES

router = APIRouter()


class BudgetBaselineRequest(BaseModel):
    """
    Budget baseline for a specific job.
    All amounts in cents (kuruş).
    If not provided, the budget agent uses auto-budget (actuals × 1.05).
    """
    budget: dict[str, int]  # { "salary": 50000000, "marketing": 10000000, ... }


@router.get("/tax/{job_id}")
async def get_tax_analysis(
    job_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return tax analysis for a completed job."""
    result = await db.execute(
        select(Report).where(
            Report.job_id == job_id,
            Report.report_format == ReportFormat.JSON,
        )
    )
    report = result.scalars().first()
    if not report or not report.data:
        raise HTTPException(status_code=404, detail="Tax data not found. Run analysis first.")
    tax = report.data.get("tax_analysis")
    if not tax:
        raise HTTPException(status_code=404, detail="Tax analysis not available for this job.")
    return {"data": tax, "error": None}


@router.get("/anomalies/{job_id}")
async def get_anomalies(
    job_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return anomaly detection results for a completed job."""
    result = await db.execute(
        select(Report).where(
            Report.job_id == job_id,
            Report.report_format == ReportFormat.JSON,
        )
    )
    report = result.scalars().first()
    if not report or not report.data:
        raise HTTPException(status_code=404, detail="Anomaly data not found. Run analysis first.")
    anomalies = report.data.get("anomalies")
    if not anomalies:
        raise HTTPException(status_code=404, detail="Anomaly analysis not available for this job.")
    return {"data": anomalies, "error": None}


@router.get("/budget/{job_id}")
async def get_budget_comparison(
    job_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return budget vs actual comparison for a completed job."""
    result = await db.execute(
        select(Report).where(
            Report.job_id == job_id,
            Report.report_format == ReportFormat.JSON,
        )
    )
    report = result.scalars().first()
    if not report or not report.data:
        raise HTTPException(status_code=404, detail="Budget data not found. Run analysis first.")
    budget = report.data.get("budget_comparison")
    if not budget:
        raise HTTPException(status_code=404, detail="Budget comparison not available for this job.")
    return {"data": budget, "error": None}


@router.post("/budget/{job_id}/rerun")
async def rerun_with_budget(
    job_id: str,
    body: BudgetBaselineRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Re-run only the budget comparison agent with a user-supplied budget baseline.
    Updates the dashboard JSON report in-place with the new budget comparison.
    """
    from app.models.analysis_job import JobStatus
    from app.agents.budget_agent import run_budget_comparison
    from app.agents.state import AgentRunConfig

    job = await db.get(AnalysisJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job.status != JobStatus.COMPLETED:
        raise HTTPException(
            status_code=409,
            detail=f"Job status is '{job.status}'. Only completed jobs can be rerun.",
        )

    # Fetch existing dashboard JSON to get transactions
    result = await db.execute(
        select(Report).where(
            Report.job_id == job_id,
            Report.report_format == ReportFormat.JSON,
        )
    )
    report = result.scalars().first()
    if not report or not report.data:
        raise HTTPException(status_code=404, detail="Analysis data not found.")

    # Build minimal state for budget agent
    dashboard = report.data
    fake_transactions = dashboard.get("recent_transactions", [])

    run_config = AgentRunConfig(budget_baseline=body.budget)
    from app.agents.state import CFOState
    minimal_state: CFOState = {
        "job_id": job_id,
        "transactions": fake_transactions,
    }

    skill_result = await run_budget_comparison(minimal_state, run_config)

    if not skill_result.ok:
        raise HTTPException(status_code=500, detail=skill_result.detail or "Budget rerun failed.")

    # Patch dashboard JSON
    new_budget = skill_result.patch.get("budget_comparison", {})
    from app.agents.report_agent import _fmt
    report.data["budget_comparison"] = {
        "categories": {
            cat: {
                "budget": _fmt(d.get("budget", 0)),
                "actual": _fmt(d.get("actual", 0)),
                "variance": _fmt(d.get("variance", 0)),
                "variance_pct": d.get("variance_pct", 0),
                "status": d.get("status"),
            }
            for cat, d in new_budget.get("categories", {}).items()
        },
        "total_variance": _fmt(new_budget.get("total_variance", 0)),
        "variance_pct": new_budget.get("variance_pct", 0),
        "over_budget_count": new_budget.get("over_budget_count", 0),
        "auto_budget": new_budget.get("auto_budget", False),
        "narrative": new_budget.get("narrative", ""),
        "alerts": new_budget.get("alerts", []),
    }

    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(report, "data")
    await db.commit()

    return {"data": report.data["budget_comparison"], "error": None}


# ── Balance Sheet ─────────────────────────────────────────────────────────────

@router.get("/balance-sheet/{job_id}")
async def get_balance_sheet(
    job_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return pro-forma balance sheet for a completed job."""
    result = await db.execute(
        select(Report).where(
            Report.job_id == job_id,
            Report.report_format == ReportFormat.JSON,
        )
    )
    report = result.scalars().first()
    if not report or not report.data:
        raise HTTPException(status_code=404, detail="Balance sheet data not found.")
    bs = report.data.get("balance_sheet")
    if not bs:
        raise HTTPException(status_code=404, detail="Balance sheet not available for this job.")
    return {"data": bs, "error": None}


# ── Financial Ratios ──────────────────────────────────────────────────────────

@router.get("/ratios/{job_id}")
async def get_financial_ratios(
    job_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return financial ratio scorecard for a completed job."""
    result = await db.execute(
        select(Report).where(
            Report.job_id == job_id,
            Report.report_format == ReportFormat.JSON,
        )
    )
    report = result.scalars().first()
    if not report or not report.data:
        raise HTTPException(status_code=404, detail="Ratios data not found.")
    ratios = report.data.get("financial_ratios")
    if not ratios:
        raise HTTPException(status_code=404, detail="Financial ratios not available for this job.")
    return {"data": ratios, "error": None}


# ── Language options ──────────────────────────────────────────────────────────

@router.get("/languages")
async def get_supported_languages() -> dict:
    """Return supported narrative languages."""
    return {
        "data": [
            {"code": code, "name": name}
            for code, name in LANG_NAMES.items()
        ],
        "error": None,
    }
