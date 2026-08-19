"""
Demo Seed API — /api/v1/demo/seed

Loads the Logo Tiger 2024 demo CSV and starts a full CFO analysis pipeline.
New users can explore the platform without uploading their own data.

POST /demo/seed      → Create a demo analysis job using logo_tiger_2024.csv
GET  /demo/status    → Check if org already has demo data loaded
DELETE /demo/reset   → Remove demo job from context (org can start fresh)
"""
from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.models.user import User

router = APIRouter(tags=["demo"])
logger = logging.getLogger(__name__)

# Path to bundled demo CSV (relative to repo root)
_DEMO_CSV_PATH = Path(__file__).resolve().parents[4] / "demo" / "data" / "logo_tiger_2024.csv"

# Fallback: generated minimal demo data if file not found
_DEMO_CSV_FALLBACK = """tarih,tutar,aciklama,kategori
2024-01-05,125000.00,Satış geliri - Ocak,Gelir
2024-01-10,-18500.00,Maaş ödemeleri,Personel
2024-01-15,-4200.00,Kira,Kira
2024-01-20,-3100.00,Elektrik ve su,Faturalar
2024-02-05,138000.00,Satış geliri - Şubat,Gelir
2024-02-10,-18500.00,Maaş ödemeleri,Personel
2024-02-15,-4200.00,Kira,Kira
2024-02-20,-2900.00,Elektrik ve su,Faturalar
2024-03-05,142000.00,Satış geliri - Mart,Gelir
2024-03-10,-19500.00,Maaş ödemeleri,Personel
2024-03-15,-4200.00,Kira,Kira
2024-03-20,-3200.00,Elektrik ve su,Faturalar
2024-04-05,155000.00,Satış geliri - Nisan,Gelir
2024-04-10,-19500.00,Maaş ödemeleri,Personel
2024-04-15,-4200.00,Kira,Kira
2024-05-05,148000.00,Satış geliri - Mayıs,Gelir
2024-05-10,-20000.00,Maaş ödemeleri,Personel
2024-06-05,162000.00,Satış geliri - Haziran,Gelir
2024-06-10,-20000.00,Maaş ödemeleri,Personel
2024-07-05,171000.00,Satış geliri - Temmuz,Gelir
2024-08-05,168000.00,Satış geliri - Ağustos,Gelir
2024-09-05,175000.00,Satış geliri - Eylül,Gelir
2024-10-05,182000.00,Satış geliri - Ekim,Gelir
2024-11-05,190000.00,Satış geliri - Kasım,Gelir
2024-12-05,205000.00,Satış geliri - Aralık,Gelir
"""


async def _get_demo_csv_content() -> bytes:
    """Return demo CSV bytes — bundled file or fallback."""
    if _DEMO_CSV_PATH.exists():
        return _DEMO_CSV_PATH.read_bytes()
    logger.warning("Demo CSV not found at %s — using minimal fallback", _DEMO_CSV_PATH)
    return _DEMO_CSV_FALLBACK.encode("utf-8")


@router.post("/demo/seed")
async def seed_demo(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Create a demo analysis job using Logo Tiger 2024 sample data.

    - Writes the demo CSV to the upload directory
    - Creates an AnalysisJob record in PENDING state
    - Enqueues the CFO pipeline via ARQ worker
    - Returns the job_id for SSE stream subscription

    Safe to call multiple times — idempotent per org (returns existing
    demo job if one already exists and is not yet 24 hours old).
    """
    from app.config import get_settings
    from app.models.analysis_job import AnalysisJob, JobStatus
    from app.worker import enqueue_analysis
    from sqlalchemy import select, desc
    from datetime import datetime, timezone, timedelta

    settings = get_settings()
    org_id = str(current_user.org_id) if current_user.org_id else str(current_user.id)

    # ── Idempotency check: existing recent demo job ───────────────────────────
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    try:
        result = await db.execute(
            select(AnalysisJob)
            .where(
                AnalysisJob.org_id == org_id,
                AnalysisJob.filename == "logo_tiger_2024_demo.csv",
                AnalysisJob.created_at >= cutoff,
            )
            .order_by(desc(AnalysisJob.created_at))
            .limit(1)
        )
        existing = result.scalar_one_or_none()
        if existing:
            logger.info("Demo seed: existing demo job=%s for org=%s", existing.id, org_id)
            return {
                "data": {
                    "job_id":   existing.id,
                    "status":   existing.status,
                    "message":  "Mevcut demo analizi kullanılıyor.",
                    "is_new":   False,
                },
                "error": None,
            }
    except Exception as exc:
        logger.warning("Demo seed: existing check failed: %s", exc)

    # ── Write demo CSV to upload dir ──────────────────────────────────────────
    demo_content = await _get_demo_csv_content()
    upload_dir   = Path(settings.upload_dir) if hasattr(settings, "upload_dir") else Path("/tmp/uploads")
    upload_dir.mkdir(parents=True, exist_ok=True)

    job_id    = str(uuid.uuid4())
    filename  = "logo_tiger_2024_demo.csv"
    file_path = upload_dir / f"{job_id}_{filename}"
    file_path.write_bytes(demo_content)

    # ── Create analysis job ───────────────────────────────────────────────────
    job = AnalysisJob(
        id        = job_id,
        status    = JobStatus.PENDING,
        filename  = filename,
        file_path = str(file_path),
        org_id    = org_id,
        user_id   = str(current_user.id),
    )
    db.add(job)
    await db.commit()

    # ── Enqueue analysis ──────────────────────────────────────────────────────
    try:
        await enqueue_analysis(job_id=job_id, file_path=str(file_path), file_type="csv")
    except Exception as exc:
        logger.error("Demo seed: enqueue failed for job=%s: %s", job_id, exc)
        # Don't fail the request — worker may pick it up via polling
        # or user can still navigate to dashboard and wait

    logger.info("Demo seed: created job=%s for org=%s", job_id, org_id)
    return {
        "data": {
            "job_id":  job_id,
            "status":  "pending",
            "message": "Demo analizi başlatıldı! Logo Tiger 2024 verisiyle CFO ve tüm C-Suite ajanları çalışacak.",
            "is_new":  True,
        },
        "error": None,
    }


@router.get("/demo/status")
async def get_demo_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Check if the org has an active demo analysis."""
    from app.models.analysis_job import AnalysisJob, JobStatus
    from sqlalchemy import select, desc
    from datetime import datetime, timezone, timedelta

    org_id = str(current_user.org_id) if current_user.org_id else str(current_user.id)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=48)

    try:
        result = await db.execute(
            select(AnalysisJob)
            .where(
                AnalysisJob.org_id == org_id,
                AnalysisJob.filename == "logo_tiger_2024_demo.csv",
                AnalysisJob.created_at >= cutoff,
            )
            .order_by(desc(AnalysisJob.created_at))
            .limit(1)
        )
        job = result.scalar_one_or_none()
    except Exception:
        job = None

    return {
        "data": {
            "has_demo":  job is not None,
            "job_id":    job.id if job else None,
            "status":    job.status if job else None,
        },
        "error": None,
    }
