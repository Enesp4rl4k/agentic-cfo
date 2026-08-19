"""
Notifications API — /api/v1/notifications/*

GET    /notifications              → List in-app notifications for current user's org
PATCH  /notifications/{id}/read   → Mark as read
PATCH  /notifications/read-all    → Mark all as read
DELETE /notifications/{id}        → Delete a notification

GET    /notifications/preferences         → Get org notification preferences
PUT    /notifications/preferences         → Update org notification preferences

POST   /notifications/test-slack          → Send a test Slack message
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, update, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.api.auth import get_current_user
from app.models.user import User
from app.models.in_app_notification import InAppNotification
from app.models.alert_preference import AlertPreference

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _require_org(user: User) -> str:
    if not user.org_id:
        raise HTTPException(status_code=400, detail="Organizasyona üye değilsiniz.")
    return user.org_id


def _notif_dict(n: InAppNotification) -> dict[str, Any]:
    return {
        "id":             n.id,
        "level":          n.level,
        "domain":         n.domain,
        "message":        n.message,
        "source":         n.source,
        "job_id":         n.job_id,
        "action":         n.action,
        "priority_score": n.priority_score,
        "is_read":        n.is_read,
        "read_at":        n.read_at.isoformat() if n.read_at else None,
        "created_at":     n.created_at.isoformat(),
    }


def _pref_dict(p: AlertPreference) -> dict[str, Any]:
    return {
        "org_id":               p.org_id,
        "channels":             json.loads(p.channels) if p.channels else ["dashboard"],
        "min_severity":         p.min_severity,
        "slack_webhook_url":    p.slack_webhook_url,
        "slack_channel":        p.slack_channel,
        "email_recipients":     json.loads(p.email_recipients) if p.email_recipients else [],
        "whatsapp_number":      getattr(p, "whatsapp_number", None),
        "daily_digest_enabled": p.daily_digest_enabled,
        "digest_hour_utc":      p.digest_hour_utc,
        "quiet_hours_start":    p.quiet_hours_start,
        "quiet_hours_end":      p.quiet_hours_end,
        "escalation_only":      p.escalation_only,
        "updated_at":           p.updated_at.isoformat(),
    }


# ── Schemas ───────────────────────────────────────────────────────────────────

class UpdatePreferencesRequest(BaseModel):
    channels: list[str] | None = None           # ["email", "slack", "whatsapp", "dashboard"]
    min_severity: str | None = None              # "info" | "warning" | "critical"
    slack_webhook_url: str | None = None
    slack_channel: str | None = None
    whatsapp_number: str | None = None          # "+905551234567" — country code required
    email_recipients: list[str] | None = None
    daily_digest_enabled: bool | None = None
    digest_hour_utc: int | None = None
    quiet_hours_start: int | None = None
    quiet_hours_end: int | None = None
    escalation_only: bool | None = None


# ── Notification endpoints ────────────────────────────────────────────────────

@router.get("/notifications")
async def list_notifications(
    unread_only: bool = Query(False),
    limit: int = Query(50, le=200),
    level: str | None = Query(None),  # filter by level
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List in-app notifications for the current user's org."""
    org_id = _require_org(current_user)

    q = select(InAppNotification).where(InAppNotification.org_id == org_id)
    if unread_only:
        q = q.where(InAppNotification.is_read == False)  # noqa: E712
    if level:
        q = q.where(InAppNotification.level == level)
    q = q.order_by(desc(InAppNotification.created_at)).limit(limit)

    result = await db.execute(q)
    notifications = result.scalars().all()

    # Unread count
    unread_result = await db.execute(
        select(InAppNotification)
        .where(InAppNotification.org_id == org_id, InAppNotification.is_read == False)  # noqa: E712
    )
    unread_count = len(unread_result.scalars().all())

    return {
        "data": {
            "notifications": [_notif_dict(n) for n in notifications],
            "unread_count": unread_count,
            "total": len(notifications),
        },
        "error": None,
    }


@router.patch("/notifications/{notification_id}/read")
async def mark_read(
    notification_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Mark a single notification as read."""
    org_id = _require_org(current_user)

    notif = await db.get(InAppNotification, notification_id)
    if not notif or notif.org_id != org_id:
        raise HTTPException(status_code=404, detail="Bildirim bulunamadı.")

    notif.is_read = True
    notif.read_at = datetime.now(timezone.utc)
    await db.commit()

    return {"data": {"id": notification_id, "is_read": True}, "error": None}


@router.patch("/notifications/read-all")
async def mark_all_read(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Mark all notifications as read for this org."""
    org_id = _require_org(current_user)
    now = datetime.now(timezone.utc)

    await db.execute(
        update(InAppNotification)
        .where(InAppNotification.org_id == org_id, InAppNotification.is_read == False)  # noqa: E712
        .values(is_read=True, read_at=now)
    )
    await db.commit()

    return {"data": {"marked_read": True}, "error": None}


@router.delete("/notifications/{notification_id}")
async def delete_notification(
    notification_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Delete a single notification."""
    org_id = _require_org(current_user)

    notif = await db.get(InAppNotification, notification_id)
    if not notif or notif.org_id != org_id:
        raise HTTPException(status_code=404, detail="Bildirim bulunamadı.")

    await db.delete(notif)
    await db.commit()

    return {"data": {"deleted": True}, "error": None}


# ── Preference endpoints ──────────────────────────────────────────────────────

@router.get("/notifications/preferences")
async def get_preferences(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get notification preferences for the current org."""
    org_id = _require_org(current_user)

    result = await db.execute(
        select(AlertPreference).where(AlertPreference.org_id == org_id)
    )
    pref = result.scalar_one_or_none()

    if not pref:
        # Return defaults
        return {
            "data": {
                "org_id": org_id,
                "channels": ["dashboard"],
                "min_severity": "warning",
                "slack_webhook_url": None,
                "slack_channel": None,
                "email_recipients": [],
                "daily_digest_enabled": True,
                "digest_hour_utc": 7,
                "quiet_hours_start": None,
                "quiet_hours_end": None,
                "escalation_only": False,
                "updated_at": None,
            },
            "error": None,
        }

    return {"data": _pref_dict(pref), "error": None}


@router.put("/notifications/preferences")
async def update_preferences(
    body: UpdatePreferencesRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Create or update notification preferences for the current org."""
    org_id = _require_org(current_user)

    result = await db.execute(
        select(AlertPreference).where(AlertPreference.org_id == org_id)
    )
    pref = result.scalar_one_or_none()

    if not pref:
        pref = AlertPreference(org_id=org_id)
        db.add(pref)

    if body.channels is not None:
        valid = {"email", "slack", "whatsapp", "dashboard"}
        pref.channels = json.dumps([c for c in body.channels if c in valid])
    if body.min_severity is not None:
        if body.min_severity not in ("info", "warning", "critical"):
            raise HTTPException(400, detail="min_severity must be info | warning | critical")
        pref.min_severity = body.min_severity
    if body.slack_webhook_url is not None:
        pref.slack_webhook_url = body.slack_webhook_url or None
    if body.slack_channel is not None:
        pref.slack_channel = body.slack_channel or None
    if body.email_recipients is not None:
        pref.email_recipients = json.dumps(body.email_recipients)
    if body.whatsapp_number is not None:
        # Basic phone number sanity check — must start with + and contain only digits
        num = body.whatsapp_number.strip()
        if num and (not num.startswith("+") or not num[1:].replace(" ", "").replace("-", "").isdigit()):
            raise HTTPException(400, detail="whatsapp_number must include country code, e.g. +905551234567")
        pref.whatsapp_number = num or None  # type: ignore[attr-defined]
    if body.daily_digest_enabled is not None:
        pref.daily_digest_enabled = body.daily_digest_enabled
    if body.digest_hour_utc is not None:
        pref.digest_hour_utc = max(0, min(23, body.digest_hour_utc))
    if body.quiet_hours_start is not None:
        pref.quiet_hours_start = body.quiet_hours_start
    if body.quiet_hours_end is not None:
        pref.quiet_hours_end = body.quiet_hours_end
    if body.escalation_only is not None:
        pref.escalation_only = body.escalation_only

    await db.commit()
    await db.refresh(pref)

    logger.info("Notification preferences updated for org=%s", org_id)
    return {"data": _pref_dict(pref), "error": None}


# ── Test endpoint ─────────────────────────────────────────────────────────────

@router.post("/notifications/test-slack")
async def test_slack(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Send a test Slack message to verify webhook configuration."""
    org_id = _require_org(current_user)

    result = await db.execute(
        select(AlertPreference).where(AlertPreference.org_id == org_id)
    )
    pref = result.scalar_one_or_none()

    webhook_url = pref.slack_webhook_url if pref else None
    if not webhook_url:
        from app.config import get_settings
        webhook_url = get_settings().slack_webhook_url or None

    if not webhook_url:
        raise HTTPException(400, detail="Slack webhook URL yapılandırılmamış.")

    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                webhook_url,
                json={
                    "text": (
                        "✅ C-Level AI — Slack entegrasyonu başarıyla test edildi!\n"
                        f"Org: `{org_id}` | {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
                    )
                },
            )
            if resp.status_code == 200:
                return {"data": {"sent": True}, "error": None}
            raise HTTPException(502, detail=f"Slack returned {resp.status_code}: {resp.text[:200]}")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, detail=f"Slack test başarısız: {exc}")
