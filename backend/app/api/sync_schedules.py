"""
Sync Schedules API — DQ-5

CRUD endpoints for managing automatic data sync schedules.

Endpoints
---------
GET    /sync/schedules              → list org's schedules
POST   /sync/schedules              → create new schedule
PUT    /sync/schedules/{id}         → update schedule
DELETE /sync/schedules/{id}         → delete schedule
POST   /sync/schedules/{id}/run     → trigger manual run immediately
GET    /sync/schedules/{id}/history → last 20 sync results
GET    /sync/sources                → list supported source types
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, text, update as sql_update, delete as sql_delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.services.scheduled_sync import (
    SyncScheduleConfig, SyncFrequency, SyncSourceType,
    get_sync_runner,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["sync"])

# ── Pydantic models ───────────────────────────────────────────────────────────

class CreateScheduleRequest(BaseModel):
    source_type: str
    frequency: str = SyncFrequency.DAILY
    hour_utc: int = 3
    enabled: bool = True
    auto_analyze: bool = True
    notify_on_completion: bool = True
    source_config: dict[str, Any] = {}


class UpdateScheduleRequest(BaseModel):
    frequency: str | None = None
    hour_utc: int | None = None
    enabled: bool | None = None
    auto_analyze: bool | None = None
    notify_on_completion: bool | None = None
    source_config: dict[str, Any] | None = None


# ── Source type metadata ──────────────────────────────────────────────────────

SOURCE_TYPES = [
    {
        "id": SyncSourceType.ERP_LOGO_TIGER,
        "label": "Logo Tiger",
        "description": "Logo Tiger ERP — işlem ve muhasebe verisi",
        "config_fields": [
            {"key": "from_date", "label": "Başlangıç Tarihi", "type": "date", "required": False},
            {"key": "to_date",   "label": "Bitiş Tarihi",     "type": "date", "required": False},
        ],
    },
    {
        "id": SyncSourceType.ERP_PARASUT,
        "label": "Paraşüt",
        "description": "Paraşüt muhasebe yazılımı",
        "config_fields": [
            {"key": "from_date", "label": "Başlangıç Tarihi", "type": "date", "required": False},
            {"key": "to_date",   "label": "Bitiş Tarihi",     "type": "date", "required": False},
        ],
    },
    {
        "id": SyncSourceType.OPEN_BANKING,
        "label": "Open Banking",
        "description": "Türk bankalarından gerçek zamanlı hesap hareketleri",
        "config_fields": [
            {"key": "bank",       "label": "Banka",      "type": "select",
             "options": ["akbank", "garanti", "isbank", "yapikredi"], "required": True},
            {"key": "account_id", "label": "Hesap ID",   "type": "text", "required": True},
        ],
    },
    {
        "id": SyncSourceType.GIB_EFATURA,
        "label": "GİB e-Fatura",
        "description": "GİB portalından e-Fatura ve e-Arşiv",
        "config_fields": [],
    },
]

FREQUENCY_OPTIONS = [
    {"id": SyncFrequency.DAILY,   "label": "Günlük",   "description": "Her gün seçilen saatte"},
    {"id": SyncFrequency.WEEKLY,  "label": "Haftalık", "description": "Her Pazartesi"},
    {"id": SyncFrequency.MONTHLY, "label": "Aylık",    "description": "Her ayın 1'i"},
    {"id": SyncFrequency.MANUAL,  "label": "Manuel",   "description": "Sadece elle tetikleme"},
]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/sync/sources")
async def list_sync_sources(
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """List all supported sync source types with config schemas."""
    return {
        "data": {
            "sources": SOURCE_TYPES,
            "frequencies": FREQUENCY_OPTIONS,
        },
        "error": None,
    }


@router.get("/sync/schedules")
async def list_schedules(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List all sync schedules for the current org."""
    org_id = str(user.org_id) if user.org_id else str(user.id)
    try:
        result = await db.execute(
            text("SELECT * FROM sync_schedules WHERE org_id = :org_id ORDER BY created_at DESC"),
            {"org_id": org_id},
        )
        rows = result.fetchall()
        schedules = [_row_to_dict(row) for row in rows]
    except Exception as e:
        logger.warning("sync_schedules table not found: %s", e)
        schedules = []

    return {"data": {"schedules": schedules}, "error": None}


@router.post("/sync/schedules", status_code=status.HTTP_201_CREATED)
async def create_schedule(
    body: CreateScheduleRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Create a new sync schedule."""
    # Validate source type
    valid_sources = [s["id"] for s in SOURCE_TYPES]
    if body.source_type not in valid_sources:
        raise HTTPException(status_code=400, detail=f"Geçersiz kaynak tipi: {body.source_type}")

    # Validate frequency
    valid_freqs = [f["id"] for f in FREQUENCY_OPTIONS]
    if body.frequency not in valid_freqs:
        raise HTTPException(status_code=400, detail=f"Geçersiz frekans: {body.frequency}")

    org_id = str(user.org_id) if user.org_id else str(user.id)
    schedule_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    try:
        await db.execute(
            text("""
                INSERT INTO sync_schedules
                (id, org_id, source_type, frequency, hour_utc, enabled,
                 auto_analyze, notify_on_completion, source_config, created_at, updated_at)
                VALUES
                (:id, :org_id, :source_type, :frequency, :hour_utc, :enabled,
                 :auto_analyze, :notify_on_completion, :source_config, :now, :now)
            """),
            {
                "id": schedule_id,
                "org_id": org_id,
                "source_type": body.source_type,
                "frequency": body.frequency,
                "hour_utc": body.hour_utc,
                "enabled": body.enabled,
                "auto_analyze": body.auto_analyze,
                "notify_on_completion": body.notify_on_completion,
                "source_config": json.dumps(body.source_config),
                "now": now,
            }
        )
        await db.commit()
    except Exception as e:
        logger.error("create_schedule failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "data": {
            "schedule_id": schedule_id,
            "source_type": body.source_type,
            "frequency": body.frequency,
            "enabled": body.enabled,
        },
        "error": None,
    }


@router.put("/sync/schedules/{schedule_id}")
async def update_schedule(
    schedule_id: str,
    body: UpdateScheduleRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Update a sync schedule."""
    org_id = str(user.org_id) if user.org_id else str(user.id)

    updates: dict[str, Any] = {"updated_at": datetime.now(timezone.utc)}
    if body.frequency is not None:
        updates["frequency"] = body.frequency
    if body.hour_utc is not None:
        updates["hour_utc"] = body.hour_utc
    if body.enabled is not None:
        updates["enabled"] = body.enabled
    if body.auto_analyze is not None:
        updates["auto_analyze"] = body.auto_analyze
    if body.notify_on_completion is not None:
        updates["notify_on_completion"] = body.notify_on_completion
    if body.source_config is not None:
        updates["source_config"] = json.dumps(body.source_config)

    try:
        set_clause = ", ".join(f"{k} = :{k}" for k in updates)
        await db.execute(
            text(f"UPDATE sync_schedules SET {set_clause} WHERE id = :id AND org_id = :org_id"),
            {**updates, "id": schedule_id, "org_id": org_id},
        )
        await db.commit()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"data": {"updated": True, "schedule_id": schedule_id}, "error": None}


@router.delete("/sync/schedules/{schedule_id}")
async def delete_schedule(
    schedule_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Delete a sync schedule."""
    org_id = str(user.org_id) if user.org_id else str(user.id)
    try:
        await db.execute(
            text("DELETE FROM sync_schedules WHERE id = :id AND org_id = :org_id"),
            {"id": schedule_id, "org_id": org_id},
        )
        await db.commit()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"data": {"deleted": True, "schedule_id": schedule_id}, "error": None}


@router.post("/sync/schedules/{schedule_id}/run")
async def trigger_manual_run(
    schedule_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Trigger an immediate manual sync run for a schedule.
    Runs synchronously — returns result when complete.
    """
    from app.config import get_settings

    org_id = str(user.org_id) if user.org_id else str(user.id)

    # Load schedule from DB
    try:
        result = await db.execute(
            text("SELECT * FROM sync_schedules WHERE id = :id AND org_id = :org_id"),
            {"id": schedule_id, "org_id": org_id},
        )
        row = result.fetchone()
    except Exception as e:
        raise HTTPException(status_code=404, detail="Schedule bulunamadı")

    if not row:
        raise HTTPException(status_code=404, detail="Schedule bulunamadı")

    row_dict = _row_to_dict(row)
    schedule = SyncScheduleConfig(
        schedule_id=schedule_id,
        org_id=org_id,
        source_type=row_dict["source_type"],
        frequency=row_dict["frequency"],
        hour_utc=row_dict["hour_utc"],
        enabled=True,   # force-run even if disabled
        source_config=row_dict.get("source_config") or {},
        auto_analyze=row_dict["auto_analyze"],
        notify_on_completion=row_dict["notify_on_completion"],
    )

    settings = get_settings()
    runner = get_sync_runner()
    sync_result = await runner.run(schedule, db, settings)

    # Update last_run in DB
    try:
        await db.execute(
            text("""
                UPDATE sync_schedules SET
                    last_run_at = :ran_at,
                    last_status = :status,
                    last_job_id = :job_id,
                    last_row_count = :rows,
                    last_health_score = :score,
                    last_error = :error,
                    updated_at = :now
                WHERE id = :id
            """),
            {
                "ran_at": sync_result.ran_at,
                "status": sync_result.status,
                "job_id": sync_result.job_id,
                "rows": sync_result.row_count,
                "score": sync_result.health_score,
                "error": sync_result.error,
                "now": datetime.now(timezone.utc),
                "id": schedule_id,
            }
        )
        await db.commit()
    except Exception as e:
        logger.warning("Failed to update schedule after run: %s", e)

    return {"data": sync_result.to_dict(), "error": None}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _row_to_dict(row: Any) -> dict[str, Any]:
    """Convert SQLAlchemy row to dict, parsing JSON fields."""
    d = dict(row._mapping)
    if isinstance(d.get("source_config"), str):
        try:
            d["source_config"] = json.loads(d["source_config"])
        except Exception:
            d["source_config"] = {}
    # Serialize datetimes
    for k in ("created_at", "updated_at", "last_run_at"):
        if isinstance(d.get(k), datetime):
            d[k] = d[k].isoformat()
    return d
