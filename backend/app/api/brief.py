"""
Executive Brief API — Morning CEO briefing endpoints.

GET  /api/v1/brief/morning
     Returns the latest pre-generated morning brief from Redis.
     Generated daily at 07:00 UTC by the scheduler.

POST /api/v1/brief/morning/generate
     Trigger on-demand brief generation (useful for testing or manual refresh).
     Runs the same logic as the scheduler job.

GET  /api/v1/brief/morning/history
     Returns the last N briefs (if stored — future: persist to DB).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/brief/morning")
async def get_morning_brief() -> dict:
    """
    Get the latest morning CEO brief.

    Generated automatically every day at 07:00 UTC by the scheduler.
    Stored in Redis with a 25h TTL (stays available all day).

    Returns the brief text, critical alert count, and top action for the day.
    """
    try:
        from app.worker import get_arq_pool
        pool = await get_arq_pool()
        raw = await pool.get("morning_brief:latest")
    except Exception as exc:
        logger.warning("Could not fetch morning brief from Redis: %s", exc)
        raw = None

    if not raw:
        return {
            "data": {
                "available": False,
                "message": (
                    "Sabah brifingi henüz hazır değil. "
                    "Her gün 07:00 UTC'de otomatik oluşturulur veya "
                    "POST /brief/morning/generate ile manuel tetikleyebilirsiniz."
                ),
                "next_scheduled": "07:00 UTC",
            },
            "error": None,
        }

    try:
        brief = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        raise HTTPException(status_code=500, detail="Brief verisi bozuk.")

    return {"data": {**brief, "available": True}, "error": None}


@router.post("/brief/morning/generate")
async def trigger_morning_brief() -> dict:
    """
    Trigger an on-demand morning brief generation.

    Runs the same logic as the daily scheduler job.
    Useful for:
    - Testing the brief system
    - Refreshing after a new analysis
    - Recovering if the scheduled job missed

    Takes ~5-15s depending on LLM latency.
    """
    try:
        from app.scheduler import _generate_morning_brief
        await _generate_morning_brief()
    except Exception as exc:
        logger.exception("On-demand morning brief generation failed")
        raise HTTPException(
            status_code=500,
            detail=f"Brief oluşturma hatası: {exc}",
        )

    # Return the freshly generated brief
    try:
        from app.worker import get_arq_pool
        pool = await get_arq_pool()
        raw = await pool.get("morning_brief:latest")
        brief = json.loads(raw) if raw else {}
    except Exception:
        brief = {}

    return {
        "data": {
            "generated": True,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            **brief,
        },
        "error": None,
    }
