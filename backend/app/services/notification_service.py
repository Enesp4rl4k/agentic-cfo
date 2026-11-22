"""
Notification Service — Deliver alerts via Slack, email, and in-app channels.

Usage:
    service = NotificationService()
    await service.deliver(decisions, org_id=org_id, db=db)

Channels:
  - slack, email, whatsapp → one outbox row each (ADR 0003). This module sends nothing:
    the outbox delivers, retries and records, and checks the recipient against the
    organisation's configured ones. The channel list is the organisation's standing preference.
  - dashboard → Persists InAppNotification rows for frontend polling

A channel that cannot be queued does not block the others.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import Any

from app.core.branding import get_brand
from app.services.alert_router import AlertDecision

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _alert_emoji(level: str) -> str:
    return {"critical": "🔴", "warning": "🟡", "info": "🔵"}.get(level, "⚪")


def _build_email_body(decisions: list[AlertDecision], org_name: str = "") -> tuple[str, str]:
    """Returns (subject, plain-text body)."""
    actionable = [d for d in decisions if d.is_actionable]
    critical = [d for d in actionable if d.alert.level == "critical"]

    subject = (
        f"🔴 [{org_name}] {len(critical)} Kritik Alert — C-Suite Dikkat"
        if critical
        else f"🟡 [{org_name}] {len(actionable)} Alert — C-Suite Özet"
    )

    lines = [
        f"C-Suite Alert Özeti — {datetime.now(UTC).strftime('%d %b %Y %H:%M UTC')}",
        "=" * 60,
        "",
    ]

    for d in actionable[:15]:
        emoji = _alert_emoji(d.alert.level)
        lines += [
            f"{emoji} [{d.alert.domain.upper()}] {d.alert.level.upper()}",
            f"   {d.alert.message}",
            f"   Kaynak: {d.alert.source} | Priority: {d.priority_score:.2f}",
            "",
        ]

    lines += [
        "—",
        f"Bu e-posta {get_brand().name} platformu tarafından otomatik olarak gönderilmiştir.",
        "Bildirim tercihlerinizi Dashboard > Settings > Notifications bölümünden yönetebilirsiniz.",
    ]

    return subject, "\n".join(lines)


# ── Main service ──────────────────────────────────────────────────────────────

class NotificationService:
    """
    Delivers alert decisions to configured channels.

    Channels resolved in priority order:
      1. Per-org AlertPreference (DB) — if available
      2. Global config fallback (Settings)
    """

    async def deliver(
        self,
        decisions: list[AlertDecision],
        org_id: str,
        org_name: str = "",
        db: Any = None,
    ) -> dict[str, int]:
        """
        Deliver actionable alert decisions to all configured channels.
        Returns a dict of {channel: count_delivered}.
        """
        actionable = [d for d in decisions if d.is_actionable]
        if not actionable:
            return {}

        results: dict[str, int] = {"slack": 0, "email": 0, "whatsapp": 0, "dashboard": 0}  # rows queued

        # Load per-org preferences (if DB available)
        prefs = await self._load_preferences(org_id, db)

        # Determine active channels
        channels = set(prefs.get("channels", ["dashboard"]))

        # Slack delivery
        if "slack" in channels:
            webhook_url = prefs.get("slack_webhook") or await self._global_slack_url()
            if webhook_url:
                sent = await self._queue_slack(actionable, webhook_url, org_id, org_name, db)
                results["slack"] = sent

        # Email delivery
        if "email" in channels:
            recipients = prefs.get("email_recipients", [])
            if recipients:
                sent = await self._queue_email(actionable, recipients, org_id, org_name, db)
                results["email"] = sent

        # WhatsApp (queued; the outbox sends via Meta Cloud API or Twilio)
        if "whatsapp" in channels:
            whatsapp_number = prefs.get("whatsapp_number")
            if whatsapp_number:
                sent = await self._queue_whatsapp(actionable, whatsapp_number, org_id, org_name, db)
                results["whatsapp"] = sent

        # In-app (always deliver dashboard notifications)
        if db is not None:
            saved = await self._save_in_app(actionable, org_id, db)
            results["dashboard"] = saved

        logger.info(
            "NotificationService: org=%s delivered slack=%d email=%d whatsapp=%d dashboard=%d",
            org_id, results["slack"], results["email"], results["whatsapp"], results["dashboard"],
        )
        return results

    # ── Slack ─────────────────────────────────────────────────────────────────

    async def _queue_slack(
        self,
        decisions: list[AlertDecision],
        webhook_url: str,
        org_id: str,
        org_name: str,
        db: Any,
    ) -> int:
        """Write the Slack message to the outbox (ADR 0003); delivery and its outcome are
        the outbox's. Returns 1 when a row was queued, 0 when nothing could be queued."""
        if db is None:
            logger.warning("Slack alert not queued: no database session for the outbox")
            return 0
        actionable = [d for d in decisions if d.is_actionable]
        if not actionable:
            return 0
        from app.services import outbox

        lines = [
            f"{_alert_emoji(d.alert.level)} [{d.alert.domain.upper()}] "
            f"{d.alert.level.upper()}: {d.alert.message[:200]}"
            for d in actionable[:8]
        ]
        severity = "critical" if any(d.alert.level == "critical" for d in actionable) else "warning"
        text = "\n".join(lines)
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        day = datetime.now(UTC).strftime("%Y%m%d")
        await outbox.enqueue_slack(
            db,
            key=f"notification:{org_id}:{day}:{digest}:slack",
            org_id=org_id,
            webhook_url=webhook_url,
            title=f"C-Suite Alert{'  |  ' + org_name if org_name else ''}",
            message=text,
            severity=severity,
            source="notification",
            source_ref=digest,
        )
        return 1

    # ── Email ─────────────────────────────────────────────────────────────────

    async def _queue_email(
        self,
        decisions: list[AlertDecision],
        recipients: list[str],
        org_id: str,
        org_name: str,
        db: Any,
    ) -> int:
        """Write one outbox row per configured recipient (ADR 0003); delivery, retry and the
        recipient check are the outbox's. Returns the number of rows queued."""
        if db is None:
            logger.warning("Alert e-mail not queued: no database session for the outbox")
            return 0
        from app.core.email_address import normalize_email
        from app.services import outbox

        subject, body = _build_email_body(decisions, org_name)
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]
        day = datetime.now(UTC).strftime("%Y%m%d")
        queued = 0
        for address in sorted({normalize_email(r) for r in recipients if r and r.strip()}):
            await outbox.enqueue(
                db,
                key=f"notification:{org_id}:{day}:{digest}:email:{address}",
                org_id=org_id,
                channel="email",
                recipient=address,
                subject=subject,
                body=body,
                source="notification",
                source_ref=digest,
            )
            queued += 1
        return queued

    # ── WhatsApp ──────────────────────────────────────────────────────────────

    async def _queue_whatsapp(
        self,
        decisions: list[AlertDecision],
        phone_number: str,
        org_id: str,
        org_name: str,
        db: Any,
    ) -> int:
        """Write the WhatsApp text for the organisation's configured number to the outbox.

        Returns 1 when a row was queued. WhatsApp has a 4096-character limit, so the text is
        compact: at most 5 alerts. Sending (Meta Cloud API or Twilio) is the outbox's."""
        actionable = [d for d in decisions if d.is_actionable]
        if db is None or not actionable:
            return 0
        from app.services import outbox

        org_label = f"[{org_name}] " if org_name else ""
        brand = get_brand()
        lines = [f"🔔 {brand.name} Alert {org_label}"]
        for d in actionable[:5]:
            lines.append(f"{_alert_emoji(d.alert.level)} {d.alert.domain.upper()}: {d.alert.message[:120]}")
        if len(actionable) > 5:
            lines.append(f"... ve {len(actionable) - 5} uyarı daha. Dashboard'da görüntüleyin.")
        if brand.app_url:
            lines.append(f"📊 Dashboard: {brand.app_url}")
        text = "\n".join(lines)
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        day = datetime.now(UTC).strftime("%Y%m%d")
        await outbox.enqueue_whatsapp(
            db,
            key=f"notification:{org_id}:{day}:{digest}:whatsapp",
            org_id=org_id,
            number=phone_number,
            subject=f"{brand.name} Alert",
            body=text,
            source="notification",
            source_ref=digest,
        )
        return 1

    # ── In-app ────────────────────────────────────────────────────────────────

    async def _save_in_app(
        self,
        decisions: list[AlertDecision],
        org_id: str,
        db: Any,
    ) -> int:
        """Save actionable alerts as InAppNotification rows."""
        try:
            from app.models.in_app_notification import InAppNotification
            count = 0
            for d in decisions:
                notif = InAppNotification(
                    org_id=org_id,
                    level=d.alert.level,
                    domain=d.alert.domain,
                    message=d.alert.message,
                    source=d.alert.source,
                    job_id=d.alert.job_id,
                    action=d.action.value,
                    priority_score=d.priority_score,
                )
                db.add(notif)
                count += 1
            await db.commit()
            return count
        except Exception as exc:
            logger.warning("In-app notification save failed: %s", exc)
            return 0

    # ── Preferences ───────────────────────────────────────────────────────────

    async def _load_preferences(self, org_id: str, db: Any) -> dict[str, Any]:
        """Load org-level notification preferences from DB."""
        if db is None:
            return {"channels": ["dashboard"]}
        try:
            from sqlalchemy import select

            from app.models.alert_preference import AlertPreference
            result = await db.execute(
                select(AlertPreference).where(AlertPreference.org_id == org_id)
            )
            pref = result.scalar_one_or_none()
            if not pref:
                return {"channels": ["dashboard"]}
            channels = json.loads(pref.channels) if pref.channels else ["dashboard"]
            recipients = json.loads(pref.email_recipients) if pref.email_recipients else []
            return {
                "channels": channels,
                "slack_webhook": pref.slack_webhook_url,
                "email_recipients": recipients,
                "whatsapp_number": pref.whatsapp_number,
                "min_severity": pref.min_severity,
                "quiet_hours_start": pref.quiet_hours_start,
                "quiet_hours_end": pref.quiet_hours_end,
            }
        except Exception as exc:
            logger.warning("Could not load alert preferences: %s", exc)
            return {"channels": ["dashboard"]}

    async def _global_slack_url(self) -> str | None:
        """Return global Slack webhook from settings (fallback)."""
        try:
            from app.config import get_settings
            url = get_settings().slack_webhook_url
            return url if url else None
        except Exception:
            return None
