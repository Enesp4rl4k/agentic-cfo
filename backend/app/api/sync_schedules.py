"""
Sync Schedules API — DQ-5

CRUD endpoints for managing automatic data sync schedules (SQLAlchemy ORM).
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.models.sync_schedule import SyncSchedule
from app.models.user import User
from app.services.scheduled_sync import (
    SyncScheduleConfig,
    SyncFrequency,
    SyncSourceType,
    get_sync_runner,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["sync"])


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


SOURCE_TYPES = [
    {
        "id": SyncSourceType.ERP_LOGO_TIGER,
        "label": "Logo Tiger",
        "description": "Logo Tiger ERP",
        "pack": "tr",
        "config_fields": [
            {"key": "from_date", "label": "From", "type": "date", "required": False},
            {"key": "to_date", "label": "To", "type": "date", "required": False},
        ],
    },
    {
        "id": SyncSourceType.ERP_PARASUT,
        "label": "Paraşüt",
        "description": "Paraşüt accounting (Turkey pack)",
        "pack": "tr",
        "config_fields": [
            {"key": "integration_id", "label": "Integration ID", "type": "text", "required": True},
        ],
    },
    {
        "id": SyncSourceType.OPEN_BANKING,
        "label": "Open Banking",
        "description": "Bank account movements",
        "pack": None,
        "config_fields": [
            {
                "key": "bank",
                "label": "Bank",
                "type": "select",
                "options": ["akbank", "garanti", "isbank", "yapikredi"],
                "required": True,
            },
            {"key": "account_id", "label": "Account ID", "type": "text", "required": True},
        ],
    },
    {
        "id": SyncSourceType.GIB_EFATURA,
        "label": "GİB e-Fatura",
        "description": "Turkey e-invoice (Turkey pack)",
        "pack": "tr",
        "config_fields": [],
    },
    {
        "id": SyncSourceType.MANUAL_CSV,
        "label": "CSV upload schedule",
        "description": "Core connector — scheduled CSV path (manual)",
        "pack": None,
        "config_fields": [],
    },
]

FREQUENCY_OPTIONS = [
    {"id": SyncFrequency.DAILY, "label": "Daily", "description": "Every day at selected hour"},
    {"id": SyncFrequency.WEEKLY, "label": "Weekly", "description": "Every Monday"},
    {"id": SyncFrequency.MONTHLY, "label": "Monthly", "description": "1st of each month"},
    {"id": SyncFrequency.MANUAL, "label": "Manual", "description": "Manual trigger only"},
]


def _schedule_to_dict(row: SyncSchedule) -> dict[str, Any]:
    cfg: Any = row.source_config or "{}"
    if isinstance(cfg, str):
        try:
            cfg = json.loads(cfg)
        except Exception:
            cfg = {}
    return {
        "id": row.id,
        "org_id": row.org_id,
        "source_type": row.source_type,
        "frequency": row.frequency,
        "hour_utc": row.hour_utc,
        "enabled": row.enabled,
        "auto_analyze": row.auto_analyze,
        "notify_on_completion": row.notify_on_completion,
        "source_config": cfg if isinstance(cfg, dict) else {},
        "last_run_at": row.last_run_at.isoformat() if row.last_run_at else None,
        "last_status": row.last_status,
        "last_job_id": row.last_job_id,
        "last_row_count": row.last_row_count,
        "last_health_score": row.last_health_score,
        "last_error": row.last_error,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.get("/sync/sources")
async def list_sync_sources(
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return {
        "data": {"sources": SOURCE_TYPES, "frequencies": FREQUENCY_OPTIONS},
        "error": None,
    }


@router.get("/sync/schedules")
async def list_schedules(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    org_id = str(user.org_id) if user.org_id else str(user.id)
    try:
        result = await db.execute(
            select(SyncSchedule)
            .where(SyncSchedule.org_id == org_id)
            .order_by(SyncSchedule.created_at.desc())
        )
        schedules = [_schedule_to_dict(r) for r in result.scalars().all()]
    except Exception as e:
        logger.warning("sync_schedules unavailable: %s", e)
        schedules = []
    return {"data": {"schedules": schedules}, "error": None}


@router.post("/sync/schedules", status_code=status.HTTP_201_CREATED)
async def create_schedule(
    body: CreateScheduleRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    valid_sources = [s["id"] for s in SOURCE_TYPES]
    if body.source_type not in valid_sources:
        raise HTTPException(status_code=400, detail=f"Invalid source type: {body.source_type}")
    valid_freqs = [f["id"] for f in FREQUENCY_OPTIONS]
    if body.frequency not in valid_freqs:
        raise HTTPException(status_code=400, detail=f"Invalid frequency: {body.frequency}")

    org_id = str(user.org_id) if user.org_id else str(user.id)
    row = SyncSchedule(
        id=str(uuid.uuid4()),
        org_id=org_id,
        source_type=body.source_type,
        frequency=body.frequency,
        hour_utc=body.hour_utc,
        enabled=body.enabled,
        auto_analyze=body.auto_analyze,
        notify_on_completion=body.notify_on_completion,
        source_config=json.dumps(body.source_config or {}),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {
        "data": {
            "schedule_id": row.id,
            "source_type": row.source_type,
            "frequency": row.frequency,
            "enabled": row.enabled,
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
    org_id = str(user.org_id) if user.org_id else str(user.id)
    row = await db.get(SyncSchedule, schedule_id)
    if not row or row.org_id != org_id:
        raise HTTPException(status_code=404, detail="Schedule not found")
    if body.frequency is not None:
        row.frequency = body.frequency
    if body.hour_utc is not None:
        row.hour_utc = body.hour_utc
    if body.enabled is not None:
        row.enabled = body.enabled
    if body.auto_analyze is not None:
        row.auto_analyze = body.auto_analyze
    if body.notify_on_completion is not None:
        row.notify_on_completion = body.notify_on_completion
    if body.source_config is not None:
        row.source_config = json.dumps(body.source_config)
    row.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return {"data": {"updated": True, "schedule_id": schedule_id}, "error": None}


@router.delete("/sync/schedules/{schedule_id}")
async def delete_schedule(
    schedule_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    org_id = str(user.org_id) if user.org_id else str(user.id)
    row = await db.get(SyncSchedule, schedule_id)
    if not row or row.org_id != org_id:
        raise HTTPException(status_code=404, detail="Schedule not found")
    await db.delete(row)
    await db.commit()
    return {"data": {"deleted": True, "schedule_id": schedule_id}, "error": None}


@router.post("/sync/schedules/{schedule_id}/run")
async def trigger_manual_run(
    schedule_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from app.config import get_settings

    org_id = str(user.org_id) if user.org_id else str(user.id)
    row = await db.get(SyncSchedule, schedule_id)
    if not row or row.org_id != org_id:
        raise HTTPException(status_code=404, detail="Schedule not found")

    row_dict = _schedule_to_dict(row)
    schedule = SyncScheduleConfig(
        schedule_id=schedule_id,
        org_id=org_id,
        source_type=row_dict["source_type"],
        frequency=row_dict["frequency"],
        hour_utc=row_dict["hour_utc"],
        enabled=True,
        source_config=row_dict.get("source_config") or {},
        auto_analyze=row_dict["auto_analyze"],
        notify_on_completion=row_dict["notify_on_completion"],
    )

    settings = get_settings()
    runner = get_sync_runner()
    sync_result = await runner.run(schedule, db, settings)

    row.last_run_at = sync_result.ran_at
    row.last_status = sync_result.status
    row.last_job_id = sync_result.job_id
    row.last_row_count = sync_result.row_count
    row.last_health_score = sync_result.health_score
    row.last_error = sync_result.error
    row.updated_at = datetime.now(timezone.utc)
    await db.commit()

    return {"data": sync_result.to_dict(), "error": None}
