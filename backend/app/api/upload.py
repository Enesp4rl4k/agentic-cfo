import os
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models.analysis_job import AnalysisJob, JobStatus

router = APIRouter()

ALLOWED_EXTENSIONS = {"pdf", "xlsx", "xls", "csv"}


def _extension(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(description="Financial document: PDF, Excel, or CSV"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Upload a financial document and create an analysis job.
    Returns job_id — poll GET /analysis/{job_id} for status.
    """
    settings = get_settings()

    ext = _extension(file.filename or "")
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '.{ext}'. Allowed: {sorted(ALLOWED_EXTENSIONS)}",
        )

    # Size check
    content = await file.read()
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size is {settings.max_upload_size_mb} MB.",
        )

    # Persist file
    job_id = str(uuid.uuid4())
    upload_dir = os.path.join(settings.storage_local_path, "uploads", job_id)
    os.makedirs(upload_dir, exist_ok=True)
    safe_name = f"document.{ext}"
    file_path = os.path.join(upload_dir, safe_name)

    with open(file_path, "wb") as f:
        f.write(content)

    # Create DB job record
    job = AnalysisJob(
        id=job_id,
        status=JobStatus.PENDING,
        filename=file.filename or safe_name,
        file_path=file_path,
        file_type=ext,
    )
    db.add(job)
    await db.commit()

    return {"data": {"job_id": job_id, "status": JobStatus.PENDING}, "error": None}
