from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.access import load_owned_job
from app.api.auth import get_current_user
from app.database import get_db
from app.models.report import Report, ReportFormat
from app.models.user import User

router = APIRouter()


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
    return {"data": report.data, "error": None}
