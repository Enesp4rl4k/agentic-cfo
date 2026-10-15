"""
Demo Seed API — /api/v1/demo/seed

Loads the Logo Tiger 2024 demo CSV and starts a full CFO analysis pipeline.
New users can explore the platform without uploading their own data.

POST /demo/guest     → One-click guest session (isolated demo org + JWT, no signup)
POST /demo/seed      → Create a demo analysis job using logo_tiger_2024.csv
GET  /demo/status    → Check if org already has demo data loaded
DELETE /demo/reset   → Remove demo job from context (org can start fresh)
"""
from __future__ import annotations

import logging
import secrets
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.models.user import User, UserRole
from app.services.demo_template import clone_demo_workspace

router = APIRouter(tags=["demo"])
logger = logging.getLogger(__name__)

# Path to bundled demo CSV (relative to repo root):
# parents[0]=api [1]=app [2]=backend [3]=repo root — parents[4] pointed at the
# parent of the repo, so the bundled file was never found and every seed
# silently fell back to the minimal 25-row CSV.
_DEMO_CSV_PATH = Path(__file__).resolve().parents[3] / "demo" / "data" / "logo_tiger_2024.csv"

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


@router.post("/demo/guest", status_code=status.HTTP_201_CREATED)
async def create_demo_guest(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """
    One-click guest demo session — try the product without signing up.

    Mints an isolated demo organization (TR locale / TRY currency) plus a
    throwaway owner user, and returns the same token shape as /auth/login so
    the frontend signs in through the existing NextAuth credentials shortcut
    (authorize() validates the access token against /auth/me).

    Every guest gets a fresh org — demos never share data. Gated by
    settings.demo_mode (secure default: disabled).
    """
    from app.api.org import _regional_defaults
    from app.config import get_settings
    from app.models.organization import Organization
    from app.services.auth import (
        create_access_token,
        create_refresh_token,
        hash_password,
    )

    settings = get_settings()
    if not settings.demo_mode:
        raise HTTPException(status_code=403, detail="Demo modu kapalı.")

    # 12 hex chars → unique-index collision risk negligible (slug + email).
    suffix = secrets.token_hex(6)

    from app.services.demo_template import GUEST_DESCRIPTION

    org = Organization(
        name=settings.demo_company_name,
        slug=f"demo-{suffix}",
        description=GUEST_DESCRIPTION,
        **_regional_defaults("TR"),
    )
    db.add(org)
    await db.flush()  # org.id before wiring the user to it

    # Random unusable password: satisfies the NOT NULL contract without ever
    # letting anyone sign in with it — the guest only holds the JWT below.
    user = User(
        email=f"demo-{suffix}@demo.local",
        hashed_password=hash_password(secrets.token_urlsafe(32)),
        full_name="Demo Misafir",
        role=UserRole.OWNER,  # owns this isolated org, like /org/create
        org_id=org.id,
    )
    user.last_login_at = datetime.now(UTC)
    db.add(user)
    await db.flush()
    await db.commit()

    # D2: clone the pre-computed golden demo workspace so the visitor lands on
    # a full dashboard. A clone failure must never block guest entry — the
    # session still works, the org just starts empty (D1 behaviour).
    try:
        outcome = await clone_demo_workspace(db, str(org.id))
        if outcome.cloned:
            logger.info(
                "Guest org=%s cloned golden demo job=%s counts=%s",
                org.id,
                outcome.job_id,
                outcome.counts,
            )
    except Exception as exc:
        logger.warning("Demo clone failed for org=%s: %s", org.id, exc)
        try:
            await db.rollback()
        except Exception:  # pragma: no cover - session already clean
            pass

    access_token = create_access_token(user.id, user.email, user.role)
    refresh_token = create_refresh_token(user.id)

    logger.info("Demo guest: org=%s user=%s", org.id, user.id)
    return {
        "data": {
            "access_token":  access_token,
            "refresh_token": refresh_token,
            "token_type":    "bearer",
            "expires_in":    1800,
            "user": {
                "user_id":   user.id,
                "email":     user.email,
                "full_name": user.full_name,
                "role":      user.role,
                "org_id":    user.org_id,
            },
        },
        "error": None,
    }


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
    from datetime import datetime, timedelta

    from sqlalchemy import desc, select

    from app.config import get_settings
    from app.models.analysis_job import AnalysisJob, JobStatus
    from app.worker import enqueue_analysis

    settings = get_settings()
    org_id = str(current_user.org_id) if current_user.org_id else str(current_user.id)

    # ── Idempotency check: existing recent demo job ───────────────────────────
    cutoff = datetime.now(UTC) - timedelta(hours=24)
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
    # There is no `upload_dir` setting — the hasattr guard silently sent every
    # demo file to a bare "/tmp/uploads", which on Windows is a stray C:	mp.
    demo_content = await _get_demo_csv_content()
    upload_dir   = Path(settings.storage_local_path)
    upload_dir.mkdir(parents=True, exist_ok=True)

    job_id    = str(uuid.uuid4())
    filename  = "logo_tiger_2024_demo.csv"
    file_path = upload_dir / f"{job_id}_{filename}"
    from app.core.atomic_io import atomic_write_bytes

    atomic_write_bytes(file_path, demo_content)

    # ── Create analysis job ───────────────────────────────────────────────────
    job = AnalysisJob(
        id        = job_id,
        status    = JobStatus.PENDING,
        filename  = filename,
        file_path = str(file_path),
        file_type = "csv",   # NOT NULL — omitting it made every seed 500
        org_id    = org_id,
        user_id   = str(current_user.id),
    )
    db.add(job)
    await db.commit()

    # ── Enqueue analysis ──────────────────────────────────────────────────────
    # `enqueue_analysis` takes (job_id, budget_input) — the file is read from the
    # AnalysisJob row above. Passing file_path/file_type here used to raise
    # TypeError into the swallowing `except` below, so the demo job was created
    # but never ran.
    try:
        await enqueue_analysis(job_id)
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


@router.delete("/demo/reset")
async def reset_demo(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Remove demo job from context (org can start fresh).

    D4 hijyen: /demo/guest klonunun simetriği — org'un demo analiz job'ları
    (+ report/transaction/anomaly/decision_log çocukları), şirket context
    snapshot'ı (Redis cache dahil) ve semantic snapshot silinir; konuk boş bir
    çalışma alanıyla başlar. Golden şablon org'u (demo-golden) 409 ile
    korunur — her klonu o besler. settings.demo_mode ile kapalıyken 403.
    """
    from sqlalchemy import select

    from app.config import get_settings
    from app.models.organization import Organization
    from app.services.demo_template import GOLDEN_SLUG, purge_demo_workspace

    if not get_settings().demo_mode:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Demo modu kapalı."
        )

    org_id = str(current_user.org_id) if current_user.org_id else str(current_user.id)

    org = (
        await db.execute(select(Organization).where(Organization.id == org_id))
    ).scalar_one_or_none()
    if org is not None and org.slug == GOLDEN_SLUG:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Golden demo şablonu sıfırlanamaz — tüm klonlar onu besler.",
        )

    counts = await purge_demo_workspace(db, org_id)
    logger.info("Demo reset: org=%s by user=%s counts=%s", org_id, current_user.email, counts)
    return {
        "data": {"org_id": org_id, "reset": True, "counts": counts},
        "error": None,
    }


@router.get("/demo/status")
async def get_demo_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Check if the org has an active demo analysis."""
    from datetime import datetime, timedelta

    from sqlalchemy import desc, select

    from app.models.analysis_job import AnalysisJob

    org_id = str(current_user.org_id) if current_user.org_id else str(current_user.id)
    cutoff = datetime.now(UTC) - timedelta(hours=48)

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
