from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.report import Report, ReportFormat, ReportType

router = APIRouter()


@router.get("/dashboard/{job_id}")
async def get_dashboard(
    job_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return the dashboard JSON payload for a completed job."""
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
