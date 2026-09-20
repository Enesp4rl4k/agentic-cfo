"""
Upload API — thin HTTP layer.

All business logic lives in app.services.upload_service.
This module handles:
  - FastAPI routing + dependency injection
  - Mapping service errors → HTTP exceptions
  - Usage metering: plan limit check before upload
  - Returning the HTTP response
"""
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.config import get_settings
from app.database import get_db
from app.models.user import User
from app.services.smmm_clients import ClientNotOwned, assert_owns_client
from app.services.upload_service import (
    FileValidationError,
    create_analysis_job,
    get_extension,
    stream_to_disk,
    validate_extension,
)
from app.services.usage_meter import (
    UsageLimitExceeded,
    check_upload_limit,
    record_usage_event,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_file(
    file: UploadFile = File(description="Financial document: PDF, Excel, or CSV"),
    client_id: str | None = Form(
        default=None,
        description=(
            "SMMM müşteri kaydı id'si — muhasebeci başka bir firmanın defterini "
            "işliyorsa. Kendi verisini analiz eden şirket için boş bırakılır."
        ),
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Upload a financial document and create an analysis job.

    - Requires authentication (Bearer JWT or X-API-Key)
    - Plan limit check: free=3/mo, starter=5/mo, pro=unlimited
    - File is streamed to disk in 64 KB chunks — no full RAM load
    - Magic bytes validated on first chunk
    - Job scoped to the authenticated user's organization
    - Returns job_id — poll GET /analysis/{job_id} for status
    """
    settings = get_settings()
    ext = get_extension(file.filename or "")
    org_id = current_user.org_id

    # Ownership is checked rather than trusted: `client_id` arrives as a plain
    # form field, and an accountant must not be able to file work against
    # somebody else's client by guessing an id.
    if client_id:
        try:
            client_id = await assert_owns_client(db, str(current_user.id), client_id)
        except ClientNotOwned as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    # ── Usage metering: check plan limit before processing ────────────────────
    if org_id:
        try:
            await check_upload_limit(org_id, db)
        except UsageLimitExceeded as exc:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail={
                    "error":   "plan_limit_exceeded",
                    "message": str(exc),
                    "resource": exc.resource,
                    "plan":     exc.plan,
                    "used":     exc.current,
                    "limit":    exc.limit,
                    "upgrade_url": "/billing",
                },
            ) from exc

    try:
        validate_extension(ext)
        upload_result = await stream_to_disk(file, ext, settings.max_upload_size_mb)
        job = await create_analysis_job(
            smmm_client_id=client_id,
            result=upload_result,
            user_id=current_user.id,
            org_id=org_id,
            db=db,
        )
    except FileValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    # Full automation: upload tamamlandığında analizi otomatik kuyruğa al.
    queued = False
    dispatch = "not_requested"
    if settings.auto_enqueue_analysis_on_upload:
        try:
            from app.worker import enqueue_analysis

            # "queued" or "inline" — not the same promise. An inline run dies
            # with the process and is never retried, so reporting both as
            # queued tells the user their work is safe when it is not.
            dispatch = await enqueue_analysis(job.id)
            queued = dispatch == "queued"
        except Exception:
            # The upload stands and the user can trigger the analysis by hand,
            # but an operator has to be able to find out why it did not start.
            logger.exception("Analysis enqueue failed for job=%s", job.id)
            queued = False
            dispatch = "failed"

    # Event bus signal (best-effort): downstream automation listeners can subscribe.
    try:
        from app.services.agent_bus import get_agent_bus

        bus = get_agent_bus()
        await bus.broadcast(
            from_agent="system",
            query_type="data_uploaded",
            payload={
                "job_id": str(job.id),
                "file_type": ext,
                "auto_queued": queued,
                "uploaded_at": datetime.now(UTC).isoformat(),
            },
            org_id=str(org_id) if org_id else f"user:{current_user.id}",
            job_id=str(job.id),
        )
    except Exception:
        # Upload path must remain resilient even if bus is unavailable.
        pass

    # ── Record successful upload event ────────────────────────────────────────
    if org_id:
        await record_usage_event(org_id, "upload", db=db)

    return {
        "data": {
            "job_id": job.id,
            "status": job.status,
            "queue_status": "queued" if queued else "not_queued",
            "auto_queued": queued,
            # How it was dispatched: queued | inline | failed | not_requested.
            # `queued` alone cannot distinguish a durable job from one running
            # in this process that will not survive a restart.
            "dispatch": dispatch,
            "durable": dispatch == "queued",
            "queued_at": datetime.now(UTC).isoformat() if queued else None,
        },
        "error": None,
    }
