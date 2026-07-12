import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.report import Report, ReportFormat

router = APIRouter()


@router.get("/reports/{job_id}")
async def list_reports(
    job_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List all generated reports for a job."""
    result = await db.execute(
        select(Report).where(Report.job_id == job_id)
    )
    reports = result.scalars().all()
    return {
        "data": [
            {
                "id": r.id,
                "job_id": r.job_id,
                "report_type": r.report_type,
                "report_format": r.report_format,
                "has_file": bool(r.file_path and os.path.exists(r.file_path)),
                "created_at": r.created_at.isoformat(),
            }
            for r in reports
        ],
        "error": None,
    }


@router.get("/reports/{report_id}/download")
async def download_report(
    report_id: str,
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    """Download a generated Excel or PDF report file."""
    report = await db.get(Report, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found.")
    if not report.file_path or not os.path.exists(report.file_path):
        raise HTTPException(status_code=404, detail="Report file not available on disk.")

    media_types = {
        ReportFormat.EXCEL: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ReportFormat.PDF: "application/pdf",
    }
    media_type = media_types.get(report.report_format, "application/octet-stream")
    filename = f"financial_report_{report.job_id}.{report.report_format}"

    return FileResponse(
        path=report.file_path,
        media_type=media_type,
        filename=filename,
    )
