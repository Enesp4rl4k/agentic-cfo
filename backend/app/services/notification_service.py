"""
Notification Service — Deliver alerts via Slack, email, and in-app channels.

Usage:
    service = NotificationService()
    await service.deliver(decisions, org_id=org_id, db=db)

Channels:
  - slack   → Incoming webhook POST (configured per-org or globally)
  - email   → SMTP / aiosmtplib (async)
  - dashboard → Persists InAppNotification rows for frontend polling

All channels fail gracefully — one channel failure does not block others.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from app.services.alert_router import AlertDecision, AlertAction

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _alert_emoji(level: str) -> str:
    return {"critical": "🔴", "warning": "🟡", "info": "🔵"}.get(level, "⚪")


def _build_slack_payload(decisions: list[AlertDecision], org_name: str = "") -> dict[str, Any]:
    """Format actionable alert decisions as a Slack Block Kit message."""
    actionable = [d for d in decisions if d.is_actionable]
    if not actionable:
        return {}

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{_alert_emoji('critical')} C-Suite Alert{'  |  ' + org_name if org_name else ''}",
            },
        },
        {"type": "divider"},
    ]

    for d in actionable[:8]:  # Slack block limit
        emoji = _alert_emoji(d.alert.level)
        action_label = "⚡ ESCALATE" if d.action == AlertAction.ESCALATE else "📋 ACTION"
        blocks.append({
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": f"*{emoji} [{d.alert.domain.upper()}] {d.alert.level.upper()}*\n{d.alert.message[:200]}",
                },
                {
                    "type": "mrkdwn",
                    "text": f"*{action_label}*\nPriority: {d.priority_score:.2f}",
                },
            ],
        })

    blocks.append({
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} · {len(actionable)} actionable alerts",
            }
        ],
    })

    return {"blocks": blocks}


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
        f"C-Suite Alert Özeti — {datetime.now(timezone.utc).strftime('%d %b %Y %H:%M UTC')}",
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
        "Bu e-posta C-Level AI platformu tarafından otomatik olarak gönderilmiştir.",
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

        results: dict[str, int] = {"slack": 0, "email": 0, "whatsapp": 0, "dashboard": 0}

        # Load per-org preferences (if DB available)
        prefs = await self._load_preferences(org_id, db)

        # Determine active channels
        channels = set(prefs.get("channels", ["dashboard"]))

        # Slack delivery
        if "slack" in channels:
            webhook_url = prefs.get("slack_webhook") or await self._global_slack_url()
            if webhook_url:
                sent = await self._send_slack(actionable, webhook_url, org_name)
                results["slack"] = sent

        # Email delivery
        if "email" in channels:
            recipients = prefs.get("email_recipients", [])
            if recipients:
                sent = await self._send_email(actionable, recipients, org_name)
                results["email"] = sent

        # WhatsApp delivery (via Meta Cloud API or Twilio)
        if "whatsapp" in channels:
            whatsapp_number = prefs.get("whatsapp_number")
            if whatsapp_number:
                sent = await self._send_whatsapp(actionable, whatsapp_number, org_name)
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

    async def _send_slack(
        self,
        decisions: list[AlertDecision],
        webhook_url: str,
        org_name: str,
    ) -> int:
        """
        POST to Slack incoming webhook using httpx (already in requirements.txt).
        Returns 1 on success, 0 on failure.
        """
        payload = _build_slack_payload(decisions, org_name)
        if not payload:
            return 0
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(webhook_url, json=payload)
                if resp.status_code == 200:
                    logger.info(
                        "Slack notification sent: %d alerts to org=%s",
                        len(decisions), org_name,
                    )
                    return 1
                else:
                    logger.warning(
                        "Slack webhook failed: HTTP %d — %s",
                        resp.status_code, resp.text[:200],
                    )
                    return 0
        except Exception as exc:
            logger.warning("Slack delivery error: %s", exc)
            return 0

    # ── Email ─────────────────────────────────────────────────────────────────

    async def _send_email(
        self,
        decisions: list[AlertDecision],
        recipients: list[str],
        org_name: str,
    ) -> int:
        """
        FAZ-3B: Send SMTP email via aiosmtplib (already in requirements.txt).

        Sends one message per recipient so partial delivery is counted correctly.
        Returns number of recipients successfully mailed.
        Skips silently if SMTP credentials are not configured.
        """
        from app.config import get_settings
        settings = get_settings()

        if not settings.smtp_user or not settings.smtp_password:
            logger.debug("SMTP credentials not configured — email delivery skipped")
            return 0

        if not recipients:
            return 0

        try:
            import aiosmtplib
            from email.mime.text import MIMEText
            from email.mime.multipart import MIMEMultipart
        except ImportError:
            logger.warning("aiosmtplib not installed — add it to requirements.txt")
            return 0

        subject, body = _build_email_body(decisions, org_name)
        delivered = 0

        for recipient in recipients:
            try:
                msg = MIMEMultipart("alternative")
                msg["Subject"] = subject
                msg["From"]    = settings.notification_from
                msg["To"]      = recipient
                msg.attach(MIMEText(body, "plain", "utf-8"))

                await aiosmtplib.send(
                    msg,
                    hostname=settings.smtp_host,
                    port=settings.smtp_port,
                    username=settings.smtp_user,
                    password=settings.smtp_password,
                    start_tls=True,
                    timeout=15,
                )
                delivered += 1
                logger.debug("Email sent to %s", recipient)

            except Exception as exc:
                # Log per-recipient failure — don't abort remaining recipients
                logger.warning("Email delivery failed for %s: %s", recipient, exc)

        if delivered > 0:
            logger.info(
                "Email notification: %d/%d recipients reached for org=%s",
                delivered, len(recipients), org_name,
            )
        return delivered

    # ── WhatsApp ──────────────────────────────────────────────────────────────

    async def _send_whatsapp(
        self,
        decisions: list[AlertDecision],
        phone_number: str,
        org_name: str,
    ) -> int:
        """
        Send WhatsApp message via Meta Cloud API (WhatsApp Business Platform).

        Configuration (set in .env):
          WHATSAPP_PHONE_NUMBER_ID  — Sender phone number ID from Meta developer console
          WHATSAPP_ACCESS_TOKEN     — Meta app access token (permanent system user token)
          WHATSAPP_API_VERSION      — API version, default "v19.0"

        Falls back to Twilio WhatsApp if Meta credentials not configured:
          TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM

        Returns 1 if sent successfully, 0 otherwise.

        Free-tier note: Meta Cloud API has a 1000 free conversations/month limit.
        Templates must be pre-approved for business-initiated messages.
        Use a text template for alerts — e.g. "C-Level AI Alert: {{1}}"
        """
        from app.config import get_settings
        settings = get_settings()

        # Build compact alert text (WhatsApp has 4096 char limit)
        actionable = [d for d in decisions if d.is_actionable]
        if not actionable:
            return 0

        org_label = f"[{org_name}] " if org_name else ""
        lines = [f"🔔 C-Level AI Alert {org_label}"]
        for d in actionable[:5]:  # max 5 alerts per message
            emoji = _alert_emoji(d.alert.level)
            lines.append(f"{emoji} {d.alert.domain.upper()}: {d.alert.message[:120]}")
        if len(actionable) > 5:
            lines.append(f"... ve {len(actionable) - 5} uyarı daha. Dashboard'da görüntüleyin.")
        lines.append("📊 Dashboard: https://app.clevelai.com")
        message_text = "\n".join(lines)

        # ── Meta Cloud API ────────────────────────────────────────────────────
        phone_number_id = getattr(settings, "whatsapp_phone_number_id", "")
        access_token    = getattr(settings, "whatsapp_access_token", "")
        api_version     = getattr(settings, "whatsapp_api_version", "v19.0")

        if phone_number_id and access_token:
            try:
                import httpx
                # Normalize phone number (must start with country code, no + or spaces)
                to_number = phone_number.lstrip("+").replace(" ", "").replace("-", "")
                payload = {
                    "messaging_product": "whatsapp",
                    "recipient_type":    "individual",
                    "to":                to_number,
                    "type":              "text",
                    "text":              {"body": message_text},
                }
                url = f"https://graph.facebook.com/{api_version}/{phone_number_id}/messages"
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(
                        url,
                        json=payload,
                        headers={
                            "Authorization": f"Bearer {access_token}",
                            "Content-Type": "application/json",
                        },
                    )
                if resp.status_code in (200, 201):
                    logger.info("WhatsApp (Meta) sent to %s for org=%s", phone_number[:6] + "***", org_name)
                    return 1
                else:
                    logger.warning("WhatsApp Meta API failed: HTTP %d — %s", resp.status_code, resp.text[:200])
            except Exception as exc:
                logger.warning("WhatsApp Meta delivery error: %s", exc)
            return 0

        # ── Twilio fallback ───────────────────────────────────────────────────
        twilio_sid    = getattr(settings, "twilio_account_sid", "")
        twilio_token  = getattr(settings, "twilio_auth_token", "")
        twilio_from   = getattr(settings, "twilio_whatsapp_from", "")  # e.g. "whatsapp:+14155238886"

        if twilio_sid and twilio_token and twilio_from:
            try:
                import httpx
                import base64
                auth = base64.b64encode(f"{twilio_sid}:{twilio_token}".encode()).decode()
                to_wa = f"whatsapp:{phone_number}" if not phone_number.startswith("whatsapp:") else phone_number
                url = f"https://api.twilio.com/2010-04-01/Accounts/{twilio_sid}/Messages.json"
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(
                        url,
                        data={"From": twilio_from, "To": to_wa, "Body": message_text},
                        headers={"Authorization": f"Basic {auth}"},
                    )
                if resp.status_code in (200, 201):
                    logger.info("WhatsApp (Twilio) sent to %s for org=%s", phone_number[:6] + "***", org_name)
                    return 1
                else:
                    logger.warning("WhatsApp Twilio failed: HTTP %d — %s", resp.status_code, resp.text[:200])
            except Exception as exc:
                logger.warning("WhatsApp Twilio delivery error: %s", exc)
            return 0

        logger.debug("WhatsApp credentials not configured — delivery skipped")
        return 0

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
            from app.models.alert_preference import AlertPreference
            from sqlalchemy import select
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
