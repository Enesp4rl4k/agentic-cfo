from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.api.auth import get_current_user
from app.models.user import User
from app.models.report import Report, ReportFormat
from app.models.analysis_job import AnalysisJob

router = APIRouter()


@router.get("/dashboard/{job_id}")
async def get_dashboard(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return the dashboard JSON payload for a completed job."""
    # Verify the job belongs to the user's org before returning data
    job = await db.get(AnalysisJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    if current_user.org_id and job.org_id and job.org_id != current_user.org_id:
        raise HTTPException(status_code=403, detail="Access denied.")

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
    return {"data": report.data, "error": None}
