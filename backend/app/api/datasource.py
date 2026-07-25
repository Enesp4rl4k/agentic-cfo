"""
Multi-domain data source upload API.

Endpoints:
  POST /api/v1/datasource/{job_id}/{domain}/{source_type}
      Upload a domain-specific file (CSV/Excel) for an existing analysis job.
      domain:      cto | chro | cmo | coo
      source_type: cloud_billing | git_log | incident_log | sprint_data |
                   headcount | attrition | compensation |
                   campaign | funnel | cohort |
                   sla | process | resource

  GET  /api/v1/datasource/{job_id}
      List all data sources attached to a job.

  DELETE /api/v1/datasource/{job_id}/{source_id}
      Remove a specific data source.
"""
from __future__ import annotations

import os
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Path, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models.analysis_job import AnalysisJob
from app.models.data_source import (
    DataSource,
    DataSourceDomain,
    DataSourceType,
    DOMAIN_SOURCE_KWARGS,
)

router = APIRouter()

# ── Validation maps ────────────────────────────────────────────────────────────

_VALID_DOMAINS: set[str] = {d.value for d in DataSourceDomain}
_VALID_TYPES: set[str]   = {t.value for t in DataSourceType}

# Which source_types belong to which domain
_DOMAIN_TYPES: dict[str, set[str]] = {
    DataSourceDomain.CFO:  {DataSourceType.BANK_STATEMENT},
    DataSourceDomain.CTO:  {
        DataSourceType.CLOUD_BILLING,
        DataSourceType.GIT_LOG,
        DataSourceType.INCIDENT_LOG,
        DataSourceType.SPRINT_DATA,
    },
    DataSourceDomain.CHRO: {
        DataSourceType.HEADCOUNT,
        DataSourceType.ATTRITION,
        DataSourceType.COMPENSATION,
    },
    DataSourceDomain.CMO:  {
        DataSourceType.CAMPAIGN,
        DataSourceType.FUNNEL,
        DataSourceType.COHORT,
    },
    DataSourceDomain.COO:  {
        DataSourceType.SLA,
        DataSourceType.PROCESS,
        DataSourceType.RESOURCE,
    },
}

_ALLOWED_EXTENSIONS = {"csv", "xlsx", "xls", "txt"}


def _ext(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


# ── POST /datasource/{job_id}/{domain}/{source_type} ──────────────────────────

@router.post("/datasource/{job_id}/{domain}/{source_type}")
async def upload_datasource(
    job_id: str = Path(..., description="Parent AnalysisJob ID"),
    domain: str = Path(..., description="Domain: cto | chro | cmo | coo"),
    source_type: str = Path(..., description="Source type, e.g. cloud_billing"),
    file: UploadFile = File(description="CSV or Excel file"),
    label: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Attach a domain-specific data source file to an existing analysis job.

    Example:
      POST /datasource/{job_id}/cto/cloud_billing
      Body: multipart/form-data with file=<AWS billing CSV>
    """
    settings = get_settings()

    # ── Validate domain & source_type ─────────────────────────────────────────
    if domain not in _VALID_DOMAINS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown domain '{domain}'. Valid: {sorted(_VALID_DOMAINS)}",
        )
    if source_type not in _VALID_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown source_type '{source_type}'. Valid: {sorted(_VALID_TYPES)}",
        )
    if source_type not in _DOMAIN_TYPES.get(domain, set()):
        raise HTTPException(
            status_code=400,
            detail=(
                f"source_type '{source_type}' does not belong to domain '{domain}'. "
                f"Valid for {domain}: {sorted(_DOMAIN_TYPES[domain])}"
            ),
        )

    # ── Validate parent job exists ────────────────────────────────────────────
    job = await db.get(AnalysisJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")

    # ── Validate file extension ───────────────────────────────────────────────
    ext = _ext(file.filename or "")
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '.{ext}'. Allowed: {sorted(_ALLOWED_EXTENSIONS)}",
        )

    # ── Read & size-check ─────────────────────────────────────────────────────
    content = await file.read()
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size is {settings.max_upload_size_mb} MB.",
        )

    # ── Persist file ──────────────────────────────────────────────────────────
    source_id = str(uuid.uuid4())
    upload_dir = os.path.join(
        settings.storage_local_path, "uploads", job_id, "datasources", domain
    )
    os.makedirs(upload_dir, exist_ok=True)
    safe_name = f"{source_type}_{source_id[:8]}.{ext}"
    file_path = os.path.join(upload_dir, safe_name)

    with open(file_path, "wb") as f:
        f.write(content)

    # ── Create DB record ──────────────────────────────────────────────────────
    source = DataSource(
        id=source_id,
        job_id=job_id,
        domain=domain,
        source_type=source_type,
        filename=file.filename or safe_name,
        file_path=file_path,
        file_size_bytes=len(content),
        label=label,
    )
    db.add(source)
    await db.commit()

    pipeline_kwarg = DOMAIN_SOURCE_KWARGS.get((domain, source_type))

    return {
        "data": {
            "source_id": source_id,
            "job_id": job_id,
            "domain": domain,
            "source_type": source_type,
            "filename": file.filename,
            "file_size_bytes": len(content),
            "pipeline_kwarg": pipeline_kwarg,
        },
        "error": None,
    }


# ── GET /datasource/{job_id} ──────────────────────────────────────────────────

@router.get("/datasource/{job_id}")
async def list_datasources(
    job_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List all data sources attached to a job, grouped by domain."""
    # Verify job exists
    job = await db.get(AnalysisJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")

    result = await db.execute(
        select(DataSource).where(DataSource.job_id == job_id)
    )
    sources = result.scalars().all()

    # Group by domain for easier frontend consumption
    grouped: dict[str, list[dict]] = {}
    for s in sources:
        grouped.setdefault(s.domain, []).append({
            "source_id": s.id,
            "source_type": s.source_type,
            "filename": s.filename,
            "file_size_bytes": s.file_size_bytes,
            "label": s.label,
            "pipeline_kwarg": s.pipeline_kwarg(),
            "created_at": s.created_at.isoformat(),
        })

    return {
        "data": {
            "job_id": job_id,
            "total": len(sources),
            "by_domain": grouped,
        },
        "error": None,
    }


# ── DELETE /datasource/{job_id}/{source_id} ───────────────────────────────────

@router.delete("/datasource/{job_id}/{source_id}")
async def delete_datasource(
    job_id: str,
    source_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Remove a data source file and its DB record."""
    result = await db.execute(
        select(DataSource).where(
            DataSource.id == source_id,
            DataSource.job_id == job_id,
        )
    )
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=404, detail="Data source not found.")

    # Remove file from disk (best-effort)
    try:
        if os.path.exists(source.file_path):
            os.remove(source.file_path)
    except OSError:
        pass  # Log but don't fail — DB record removal is more important

    await db.delete(source)
    await db.commit()

    return {"data": {"deleted": source_id}, "error": None}
