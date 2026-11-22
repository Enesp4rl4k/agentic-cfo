"""The outbox sender's clients: the only code that talks to a mail, WhatsApp or Slack endpoint.

Nothing else in `app/` may import an SMTP client, call a messaging provider, or send through
`AlertDispatcher` (tests/test_architecture_fitness.py fails on it). Business code writes an
outbox row (`app.services.outbox`); `deliver_pending` calls the functions here and records the
outcome on the row.

Outcome words, shared by every sender: "sent", "sent:noop" (recorded, nothing left the
process), "not_configured" (no credentials: retrying cannot help) or "failed:<reason>".

Mode: in development (SQLite) and under pytest the sender is a recorded no-op unless
`OUTBOX_TRANSPORT=live`; in production it is live unless `OUTBOX_TRANSPORT=noop`. A no-op
delivery is written to `RECORDED` and the log, and marked on the row as transport "noop".
What the real sender needs: SMTP_HOST/SMTP_PORT/SMTP_USER/SMTP_PASSWORD/NOTIFICATION_FROM for
e-mail; WHATSAPP_PHONE_NUMBER_ID + WHATSAPP_ACCESS_TOKEN (Meta) or the TWILIO_* trio for
WhatsApp; SLACK_BOT_TOKEN for bot replies.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from collections import deque
from email.mime.text import MIMEText
from typing import Any

logger = logging.getLogger(__name__)

# What a no-op delivery would have sent, newest last: (channel, recipient, subject). The body
# is not kept: it can hold a one-time link.
RECORDED: deque[tuple[str, str, str]] = deque(maxlen=200)


def live() -> bool:
    """Whether a send may leave the process."""
    from app.config import get_settings

    settings = get_settings()
    if settings.outbox_transport == "live":
        return True
    if settings.outbox_transport == "noop":
        return False
    if "PYTEST_CURRENT_TEST" in os.environ:
        return False
    return not settings.use_sqlite


def _record(channel: str, recipient: str, subject: str) -> str:
    RECORDED.append((channel, recipient, subject))
    logger.info("outbox no-op: %s to %s recorded, not sent", channel, recipient[:3] + "***")
    return "sent:noop"


def _one_line(value: str) -> bool:
    return "\r" not in value and "\n" not in value


async def send_plain_email(recipient: str, subject: str, body: str) -> str:
    """Send one plain-text message and say what happened."""
    if not _one_line(recipient) or not _one_line(subject) or " " in recipient:
        return "failed:header_injection_refused"
    if not live():
        return _record("email", recipient, subject)
    from app.config import get_settings

    settings = get_settings()
    if not settings.smtp_user or not settings.smtp_password:
        return "not_configured"
    try:
        import aiosmtplib
    except ImportError:
        return "failed:aiosmtplib is not installed"
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = settings.notification_from
    msg["To"] = recipient
    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_user,
            password=settings.smtp_password,
            start_tls=True,
            timeout=15,
        )
    except Exception as exc:  # the reason is kept on the outbox row
        return f"failed:{type(exc).__name__}: {exc}"
    return "sent"


async def send_whatsapp(recipient: str, body: str) -> str:
    """One WhatsApp text through the Meta Cloud API, or Twilio when Meta is not configured."""
    if not live():
        return _record("whatsapp", recipient, "")
    import httpx

    from app.config import get_settings

    settings = get_settings()
    try:
        if settings.whatsapp_phone_number_id and settings.whatsapp_access_token:
            to_number = recipient.lstrip("+").replace(" ", "").replace("-", "")
            url = (
                f"https://graph.facebook.com/{settings.whatsapp_api_version}"
                f"/{settings.whatsapp_phone_number_id}/messages"
            )
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    url,
                    json={
                        "messaging_product": "whatsapp", "recipient_type": "individual",
                        "to": to_number, "type": "text", "text": {"body": body},
                    },
                    headers={"Authorization": f"Bearer {settings.whatsapp_access_token}"},
                )
        elif settings.twilio_account_sid and settings.twilio_auth_token and settings.twilio_whatsapp_from:
            auth = base64.b64encode(
                f"{settings.twilio_account_sid}:{settings.twilio_auth_token}".encode()
            ).decode()
            to_wa = recipient if recipient.startswith("whatsapp:") else f"whatsapp:{recipient}"
            url = f"https://api.twilio.com/2010-04-01/Accounts/{settings.twilio_account_sid}/Messages.json"
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    url,
                    data={"From": settings.twilio_whatsapp_from, "To": to_wa, "Body": body},
                    headers={"Authorization": f"Basic {auth}"},
                )
        else:
            return "not_configured"
    except Exception as exc:
        return f"failed:{type(exc).__name__}: {exc}"
    return "sent" if resp.status_code in (200, 201) else f"failed:http_{resp.status_code}"


async def send_slack_bot(spec_json: str) -> str:
    """One chat.postMessage reply of the Slack bot; `spec_json` is {"channel", "text", "blocks"?}."""
    try:
        spec: dict[str, Any] = json.loads(spec_json)
        channel = str(spec["channel"])
        text = str(spec["text"])
    except (ValueError, KeyError, TypeError) as exc:
        return f"failed:bad_payload: {exc}"
    if not live():
        return _record("slack_bot", channel, "")
    import httpx

    from app.config import get_settings

    token = get_settings().slack_bot_token
    if not token:
        return "not_configured"
    message: dict[str, Any] = {"channel": channel, "text": text}
    if spec.get("blocks"):
        message["blocks"] = spec["blocks"]
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://slack.com/api/chat.postMessage",
                headers={"Authorization": f"Bearer {token}"},
                json=message,
            )
    except Exception as exc:
        return f"failed:{type(exc).__name__}: {exc}"
    if resp.status_code != 200:
        return f"failed:http_{resp.status_code}"
    try:
        ok = bool(resp.json().get("ok"))
    except ValueError:
        ok = False
    return "sent" if ok else "failed:slack_not_ok"
