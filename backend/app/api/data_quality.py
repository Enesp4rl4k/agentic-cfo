"""
Data Quality API — CSV validation endpoints (DQ-1, DQ-2, DQ-3)

Endpoints
---------
POST /data-quality/validate
    Upload a CSV file for validation WITHOUT starting analysis.
    Returns ValidationResult with health score, column mapping, issues.

POST /data-quality/validate-and-upload
    Validate first, then start analysis if score >= threshold.
    Returns both validation result + job_id (if created).

GET  /data-quality/field-mapping-hints
    Returns all supported field names and their CSV column aliases.
    Used by the frontend Auto-mapping UI (DQ-2).

POST /data-quality/accept-mapping
    Accept a user-confirmed column mapping and start analysis.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.config import get_settings
from app.database import get_db
from app.models.user import User
from app.services.csv_validator import FIELD_MAP_CANDIDATES, CSVValidator

logger = logging.getLogger(__name__)
router = APIRouter(tags=["data-quality"])

# Minimum health score to auto-proceed to analysis
MIN_AUTO_PROCEED_SCORE = 40


# ── Request / Response models ─────────────────────────────────────────────────

class AcceptMappingRequest(BaseModel):
    """User-confirmed column mapping to override auto-detection."""
    job_id: str | None = None
    filename: str
    column_mapping: dict[str, str]   # system_field → csv_column_name
    # Raw CSV content (base64 if binary, or plain text)
    csv_content: str
    encoding: str = "utf-8"


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/data-quality/validate")
async def validate_csv(
    file: UploadFile = File(description="CSV file to validate"),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Validate a CSV file and return data quality report.
    Does NOT create an analysis job.

    Use this endpoint to show users a preview of data quality issues
    before they commit to uploading.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Dosya adı gereklidir.")

    ext = file.filename.lower().rsplit(".", 1)[-1] if "." in file.filename else ""
    if ext not in ("csv", "txt", "tsv"):
        raise HTTPException(
            status_code=400,
            detail=f"Sadece CSV dosyaları doğrulanabilir. Alınan: .{ext}"
        )

    settings = get_settings()
    max_bytes = settings.max_upload_size_mb * 1024 * 1024

    file_bytes = await file.read()
    if len(file_bytes) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Dosya çok büyük. Maksimum: {settings.max_upload_size_mb}MB"
        )

    try:
        result = CSVValidator.validate(file_bytes, filename=file.filename)
    except Exception as e:
        logger.error("CSV validation error: %s", e)
        raise HTTPException(status_code=422, detail=f"Dosya doğrulanamadı: {e}")

    return {
        "data": result.to_dict(),
        "error": None,
    }


@router.post("/data-quality/validate-and-upload")
async def validate_and_upload(
    file: UploadFile = File(description="CSV file to validate and optionally analyze"),
    min_score: int = MIN_AUTO_PROCEED_SCORE,
    force: bool = False,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Two-phase upload:
    1. Validate the CSV and return data quality report.
    2. If health_score >= min_score (or force=True), create analysis job.

    Returns:
        validation: full ValidationResult
        job_id: str | None — only set if analysis was started
        started: bool
        blocked_reason: str | None — why analysis was not started
    """
    import io as _io

    from app.services.upload_service import (
        FileValidationError,
        create_analysis_job,
        get_extension,
        stream_to_disk,
        validate_extension,
    )

    if not file.filename:
        raise HTTPException(status_code=400, detail="Dosya adı gereklidir.")

    settings = get_settings()
    max_bytes = settings.max_upload_size_mb * 1024 * 1024

    file_bytes = await file.read()
    if len(file_bytes) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Dosya çok büyük. Maksimum: {settings.max_upload_size_mb}MB"
        )

    # Phase 1: validate
    ext = get_extension(file.filename)
    validation_result = None
    if ext == "csv":
        try:
            validation_result = CSVValidator.validate(file_bytes, filename=file.filename)
        except Exception as e:
            logger.warning("CSV validation failed (non-fatal): %s", e)

    # Phase 2: decide whether to start analysis
    job_id: str | None = None
    started = False
    blocked_reason: str | None = None

    should_proceed = force or (
        validation_result is None or
        validation_result.health_score >= min_score
    )

    if not should_proceed:
        blocked_reason = (
            f"Veri kalitesi skoru çok düşük ({validation_result.health_score}/100). "
            f"Devam etmek için score >= {min_score} olmalı veya force=true geçin."
        )
    else:
        # Create analysis job (same as /upload endpoint)
        try:
            # Re-wrap bytes as UploadFile-compatible object for stream_to_disk
            fake_file = UploadFile(
                filename=file.filename,
                file=_io.BytesIO(file_bytes),
            )
            validate_extension(ext)
            upload_result = await stream_to_disk(fake_file, ext, settings.max_upload_size_mb)
            job = await create_analysis_job(
                result=upload_result,
                user_id=user.id,
                org_id=user.org_id,
                db=db,
            )
            job_id = job.id
            started = True
        except FileValidationError as exc:
            blocked_reason = str(exc)
        except Exception as exc:
            logger.error("Upload failed after validation: %s", exc)
            blocked_reason = f"Dosya yükleme başarısız: {exc}"

    return {
        "data": {
            "validation": validation_result.to_dict() if validation_result else None,
            "job_id": job_id,
            "started": started,
            "blocked_reason": blocked_reason,
        },
        "error": None,
    }


@router.get("/data-quality/field-mapping-hints")
async def get_field_mapping_hints(
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Return all supported system field names and their recognized CSV column aliases.
    Used by the frontend Auto-mapping UI (DQ-2).
    """
    return {
        "data": {
            "fields": [
                {
                    "field": field_name,
                    "required": field_name in ("date", "amount"),
                    "aliases": aliases,
                    "description": _field_description(field_name),
                }
                for field_name, aliases in FIELD_MAP_CANDIDATES.items()
            ]
        },
        "error": None,
    }


@router.post("/data-quality/accept-mapping")
async def accept_column_mapping(
    body: AcceptMappingRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Accept user-confirmed column mapping and start analysis.
    Called after the user reviews and adjusts the auto-detected mapping in the UI (DQ-2).
    """
    import base64
    import io as _io

    from app.services.upload_service import (
        FileValidationError,
        create_analysis_job,
        get_extension,
        stream_to_disk,
        validate_extension,
    )

    # Decode CSV content
    try:
        try:
            csv_bytes = base64.b64decode(body.csv_content)
        except Exception:
            csv_bytes = body.csv_content.encode(body.encoding, errors="replace")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"CSV içeriği okunamadı: {e}")

    ext = get_extension(body.filename)
    if ext != "csv":
        raise HTTPException(status_code=400, detail="Sadece CSV dosyaları desteklenir.")

    settings = get_settings()

    try:
        fake_file = UploadFile(
            filename=body.filename,
            file=_io.BytesIO(csv_bytes),
        )
        validate_extension(ext)
        upload_result = await stream_to_disk(fake_file, ext, settings.max_upload_size_mb)

        # Store the confirmed mapping in job metadata
        job = await create_analysis_job(
            result=upload_result,
            user_id=user.id,
            org_id=user.org_id,
            db=db,
        )

        # Persist mapping in job metadata (for the pipeline to use)
        if job and body.column_mapping:

            from sqlalchemy import update

            from app.models.analysis_job import AnalysisJob
            existing_meta = job.result_metadata or {}
            existing_meta["column_mapping"] = body.column_mapping
            await db.execute(
                update(AnalysisJob)
                .where(AnalysisJob.id == job.id)
                .values(result_metadata=existing_meta)
            )
            await db.commit()

    except FileValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("accept_column_mapping failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "data": {
            "job_id": job.id,
            "column_mapping": body.column_mapping,
            "status": job.status,
        },
        "error": None,
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _field_description(field_name: str) -> str:
    descriptions = {
        "date":        "İşlem tarihi (zorunlu)",
        "amount":      "İşlem tutarı (zorunlu)",
        "description": "İşlem açıklaması / narrasyon",
        "category":    "Kategori veya hesap kodu",
        "reference":   "Referans / fiş / fatura numarası",
    }
    return descriptions.get(field_name, field_name)
