import os

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.report import Report, ReportFormat

router = APIRouter()


# NOTE: Download route MUST be registered before the list route.
# FastAPI matches routes in registration order — "/reports/{id}/download"
# must come before "/reports/{id}" or it will never be reached.

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


@router.get("/reports/{job_id}/executive-pdf")
async def download_executive_report(
    job_id: str,
    company_name: str = Query(default="Şirket", description="Rapor başlığındaki şirket adı"),
    period: str | None = Query(default=None, description="Dönem etiketi, örn. '2024-Q1'"),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """
    Generate and download a board-ready executive report PDF.

    Creates a professional single-page A4 PDF with:
    - KPI özet strip (ciro, brüt kâr, FAVÖK, net kâr, nakit)
    - CFO narrative
    - Aylık nakit akışı tablosu
    - Faaliyet giderleri dökümü
    - 12 aylık tahmin senaryoları
    - Uyarı özeti

    Suitable for direct use in management board presentations.
    """
    from app.models.report import ReportFormat

    # Load dashboard JSON
    result = await db.execute(
        select(Report)
        .where(Report.job_id == job_id, Report.report_format == ReportFormat.JSON)
        .order_by(desc(Report.created_at))
        .limit(1)
    )
    report = result.scalar_one_or_none()
    if not report or not report.data:
        raise HTTPException(
            status_code=404,
            detail=f"Job '{job_id}' için analiz verisi bulunamadı. Önce analiz çalıştırın.",
        )

    try:
        from app.services.executive_report_pdf import generate_executive_report
        pdf_bytes = generate_executive_report(
            dashboard=report.data,
            company_name=company_name,
            period=period,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    safe_name = company_name.lower().replace(" ", "-").replace(".", "")[:30]
    filename  = f"{safe_name}-yonetim-raporu.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(pdf_bytes)),
        },
    )
