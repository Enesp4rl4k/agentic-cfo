from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.access import load_owned_job
from app.api.auth import get_current_user
from app.database import get_db
from app.models.report import Report, ReportFormat
from app.models.user import User
from app.platform.provenance import provenance_block

router = APIRouter()

# 1.3 (U7): how each CFO section was produced. The pipeline computes pnl /
# kpis / cashflow / multi_period from the parsed file or pasted transactions,
# evaluates the tax block with deterministic rules, takes the budget plan from
# user input, and extrapolates the forecast — say which is which so the metric
# cards can badge themselves as Gerçek / Tahmin (DESIGN.md: "distinguish real,
# estimated and benchmark data close to the metric"). Read-time stamping on
# purpose: every stored report — golden demo replays included — gets the
# correct label without a data migration.
SECTION_PROVENANCE: dict[str, str] = {
    "kpis": "real",
    "pnl": "real",
    "cashflow": "real",
    "multi_period": "real",
    "recent_transactions": "real",
    # Fixed-rate estimates (KDV %20, stopaj, SGK, kurumlar) — "rule_based"
    # badged them "Gerçek". The ledger's actual payments are tax.paid, which
    # the tax page labels on its own card (plan v8 §A2).
    "tax": "estimated",
    "budget": "manual",
    "forecast": "estimated",
}


@router.get("/dashboard/{job_id}")
async def get_dashboard(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return the dashboard JSON payload for a completed job."""
    # Verify the job belongs to the user's org before returning data
    # The old test skipped itself when either side had no organisation.
    await load_owned_job(db, job_id, current_user)

    result = await db.execute(
        select(Report).where(
            Report.job_id == job_id,
            Report.report_format == ReportFormat.JSON,
        )
    )
    report = result.scalars().first()
    if not report:
        raise HTTPException(
            status_code=404,
            detail="Dashboard data not found. Ensure the analysis job has completed.",
        )
    data = dict(report.data or {})
    data["provenance"] = {
        name: provenance_block(source, None)
        for name, source in SECTION_PROVENANCE.items()
    }
    return {"data": data, "error": None}
