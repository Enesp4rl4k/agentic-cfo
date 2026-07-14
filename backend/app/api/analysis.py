import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.analysis_job import AnalysisJob, JobStatus
from app.models.transaction import Transaction
from app.models.report import Report, ReportType, ReportFormat
from app.agents.orchestrator import run_cfo_pipeline
from app.agents.state import AgentRunConfig

router = APIRouter()


async def _run_and_persist(job_id: str, language: str = "tr") -> None:
    """Background task: run CFO pipeline and persist results to DB."""
    from app.database import session_factory

    async with session_factory()() as db:
        job = await db.get(AnalysisJob, job_id)
        if not job:
            return
        job.status = JobStatus.ANALYZING
        job.updated_at = datetime.now(timezone.utc)
        await db.commit()

        try:
            result = await run_cfo_pipeline(
                job_id=job_id,
                file_path=job.file_path,
                file_type=job.file_type,
                run_config=AgentRunConfig(require_review=False, language=language),
            )

            # Persist transactions
            for tx_data in result.get("transactions") or []:
                tx = Transaction(
                    job_id=job_id,
                    amount_kurus=tx_data.get("amount_cents", 0),
                    currency=tx_data.get("currency", "USD"),
                    type=tx_data.get("type", "expense"),
                    category=tx_data.get("category", "other_expense"),
                    description=tx_data.get("description", ""),
                    vendor=tx_data.get("vendor"),
                    transaction_date=datetime.fromisoformat(tx_data["transaction_date"])
                    if tx_data.get("transaction_date")
                    else datetime.now(timezone.utc),
                    raw_text=tx_data.get("raw_text"),
                    confidence=tx_data.get("confidence"),
                )
                db.add(tx)

            # Persist dashboard JSON report
            if result.get("dashboard_json"):
                db.add(Report(
                    job_id=job_id,
                    report_type=ReportType.FULL,
                    report_format=ReportFormat.JSON,
                    data=result["dashboard_json"],
                ))

            # Persist Excel report reference
            report_paths = result.get("report_paths") or {}
            if report_paths.get("xlsx"):
                db.add(Report(
                    job_id=job_id,
                    report_type=ReportType.FULL,
                    report_format=ReportFormat.EXCEL,
                    file_path=report_paths["xlsx"],
                ))

            # Update job status
            logs_serializable = [
                {"step": lg.step, "ok": lg.ok, "detail": lg.detail, "confidence": lg.confidence}
                for lg in (result.get("logs") or [])
            ]
            job.status = (
                JobStatus.AWAITING_REVIEW if result.get("awaiting_review") else JobStatus.COMPLETED
            )
            job.logs = logs_serializable
            job.min_confidence = result.get("min_confidence")
            job.awaiting_review = bool(result.get("awaiting_review"))
            job.completed_at = datetime.now(timezone.utc)
            job.updated_at = datetime.now(timezone.utc)
            await db.commit()

        except Exception as exc:
            job.status = JobStatus.FAILED
            job.error_message = str(exc)
            job.updated_at = datetime.now(timezone.utc)
            await db.commit()
            raise


@router.post("/analyze/{job_id}")
async def start_analysis(
    job_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    language: str = "tr",
) -> dict:
    """
    Trigger CFO analysis pipeline for an uploaded job.
    language: tr | en | de  — determines narrative language for all agents.
    """
    from app.agents.i18n import validate_language
    lang = validate_language(language)
    job = await db.get(AnalysisJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job.status not in (JobStatus.PENDING, JobStatus.FAILED):
        raise HTTPException(
            status_code=409,
            detail=f"Job is already in status '{job.status}'. Cannot re-run.",
        )
    background_tasks.add_task(_run_and_persist, job_id, lang)
    return {"data": {"job_id": job_id, "status": "queued", "language": lang}, "error": None}


@router.get("/analysis/{job_id}")
async def get_analysis_status(
    job_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Poll job status and get logs."""
    job = await db.get(AnalysisJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return {
        "data": {
            "job_id": job.id,
            "status": job.status,
            "filename": job.filename,
            "awaiting_review": job.awaiting_review,
            "min_confidence": float(job.min_confidence) if job.min_confidence else None,
            "logs": job.logs or [],
            "error": job.error_message,
            "created_at": job.created_at.isoformat(),
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        },
        "error": None,
    }


@router.post("/analysis/{job_id}/approve")
async def approve_review(
    job_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Human approval — clear the awaiting_review flag to allow the pipeline to proceed."""
    job = await db.get(AnalysisJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    if not job.awaiting_review:
        raise HTTPException(status_code=409, detail="Job is not awaiting review.")
    job.awaiting_review = False
    job.status = JobStatus.PENDING
    job.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return {"data": {"job_id": job_id, "approved": True}, "error": None}
