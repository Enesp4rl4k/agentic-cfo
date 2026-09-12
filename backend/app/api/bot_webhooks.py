"""
Bot Webhooks — WhatsApp Business Cloud API & Slack Events API

Endpoints:
  GET  /webhooks/whatsapp  — Hub verification challenge (Meta requires this)
  POST /webhooks/whatsapp  — Inbound WhatsApp messages
  POST /webhooks/slack     — Slack Events API + Interactive Actions
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.services.bot_gateways import OmnichannelCFOBotGateway

router = APIRouter(tags=["bot-webhooks"])
logger = logging.getLogger(__name__)


# ── WhatsApp Hub Verification ─────────────────────────────────────────────────

@router.get("/webhooks/whatsapp")
async def whatsapp_verify(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
) -> Response:
    """
    WhatsApp Cloud API webhook verification.
    Meta calls this GET endpoint once when you register the webhook URL.
    """
    settings = get_settings()
    if hub_mode == "subscribe" and hub_verify_token == settings.whatsapp_verify_token:
        logger.info("WhatsApp webhook verified.")
        return Response(content=hub_challenge, media_type="text/plain")
    raise HTTPException(status_code=403, detail="Verification failed.")


# ── WhatsApp Inbound Messages ─────────────────────────────────────────────────

@router.post("/webhooks/whatsapp", status_code=200)
async def whatsapp_inbound(request: Request, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """
    Receives inbound WhatsApp messages from Meta Cloud API.
    Dispatches to OmnichannelCFOBotGateway and sends reply via httpx.

    Meta signs each post with the App Secret. This route verified nothing, so
    anyone could post a message as any sender and have the bot answer it.
    """
    settings = get_settings()
    body_bytes = await request.body()
    if not settings.whatsapp_app_secret:
        # Closed, not open: an unconfigured secret is not permission to skip it.
        raise HTTPException(status_code=503, detail="WhatsApp webhook yapılandırılmamış (WHATSAPP_APP_SECRET).")
    expected = "sha256=" + hmac.new(
        settings.whatsapp_app_secret.encode(), body_bytes, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, request.headers.get("X-Hub-Signature-256", "")):
        raise HTTPException(status_code=403, detail="Invalid WhatsApp signature.")
    import json as _json

    payload = _json.loads(body_bytes or b"{}")

    try:
        # Navigate the Cloud API payload structure
        entry = payload.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])
        if not messages:
            return {"status": "no_messages"}

        msg = messages[0]
        sender_id = msg.get("from", "")
        message_text = msg.get("text", {}).get("body", "") if msg.get("type") == "text" else ""

        if not message_text:
            return {"status": "non_text_message"}

        # Load basic financial context (use defaults if no active job)
        financial_context: dict[str, Any] = {}

        # Dispatch to gateway
        bot_response = OmnichannelCFOBotGateway.handle_command(
            channel="whatsapp",
            sender_id=sender_id,
            message_text=message_text,
            financial_context=financial_context,
        )

        # Send reply via WhatsApp Cloud API
        if settings.whatsapp_access_token and settings.whatsapp_phone_number_id:
            wa_payload = {
                "messaging_product": "whatsapp",
                "to": sender_id,
                "type": "text",
                "text": {"body": bot_response.reply_text},
            }
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"https://graph.facebook.com/{settings.whatsapp_api_version}"
                    f"/{settings.whatsapp_phone_number_id}/messages",
                    headers={
                        "Authorization": f"Bearer {settings.whatsapp_access_token}",
                        "Content-Type": "application/json",
                    },
                    json=wa_payload,
                )
                resp.raise_for_status()
            logger.info("WhatsApp reply sent to %s", sender_id)
        else:
            logger.warning("WhatsApp credentials not configured — skipping send. Reply: %s", bot_response.reply_text)

        return {"status": "handled"}

    except Exception as exc:
        logger.error("WhatsApp webhook error: %s", exc, exc_info=True)
        # Always return 200 to Meta or they'll retry endlessly
        return {"status": "error", "detail": str(exc)}


# ── Slack Events API ──────────────────────────────────────────────────────────

def _verify_slack_signature(request_body: bytes, timestamp: str, signature: str, signing_secret: str) -> bool:
    """Verify Slack request using HMAC-SHA256 signing secret."""
    base = f"v0:{timestamp}:{request_body.decode('utf-8')}"
    expected = "v0=" + hmac.new(
        signing_secret.encode(), base.encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


@router.post("/webhooks/slack", status_code=200)
async def slack_events(request: Request, db: AsyncSession = Depends(get_db)) -> Any:
    """
    Receives Slack Events API payloads and interactive action callbacks.
    Verifies request signature using Slack signing secret.
    """
    settings = get_settings()
    body_bytes = await request.body()

    # Signature verification — required. It used to be skipped whenever the
    # secret was unset, which made an unconfigured deployment accept anything.
    if not settings.slack_signing_secret:
        raise HTTPException(status_code=503, detail="Slack webhook yapılandırılmamış (SLACK_SIGNING_SECRET).")
    ts = request.headers.get("X-Slack-Request-Timestamp", "")
    sig = request.headers.get("X-Slack-Signature", "")
    if not _verify_slack_signature(body_bytes, ts, sig, settings.slack_signing_secret):
        raise HTTPException(status_code=403, detail="Invalid Slack signature.")

    payload: dict[str, Any] = {}
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        payload = json.loads(body_bytes)
    elif "application/x-www-form-urlencoded" in content_type:
        # Slack interactive actions send URL-encoded "payload" field
        from urllib.parse import parse_qs
        parsed = parse_qs(body_bytes.decode())
        payload = json.loads(parsed.get("payload", ["{}"])[0])

    # URL verification challenge (Slack sends this once on setup)
    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge")}

    # Interactive action (button click: approve/reject)
    if payload.get("type") == "block_actions":
        actions = payload.get("actions", [])
        for action in actions:
            action_value = action.get("value", "")
            user_id = payload.get("user", {}).get("id", "")
            channel_id = payload.get("channel", {}).get("id", "")
            logger.info("Slack interactive action: %s by %s", action_value, user_id)

            # Wire to action_runner for approve/reject
            if action_value.startswith(("approve_", "reject_")):
                action_id = action_value.replace("approve_", "").replace("reject_", "")
                reply_text = (
                    f"✅ `{action_id}` onaylandı ve sisteme iletildi."
                    if action_value.startswith("approve_")
                    else f"❌ `{action_id}` reddedildi."
                )
                # Reply in the same Slack channel
                if settings.slack_bot_token and channel_id:
                    async with httpx.AsyncClient(timeout=10) as client:
                        await client.post(
                            "https://slack.com/api/chat.postMessage",
                            headers={"Authorization": f"Bearer {settings.slack_bot_token}"},
                            json={"channel": channel_id, "text": reply_text},
                        )
        return {"status": "ok"}

    # Message event
    event = payload.get("event", {})
    if event.get("type") == "message" and not event.get("bot_id"):
        sender_id = event.get("user", "")
        channel_id = event.get("channel", "")
        message_text = event.get("text", "")

        bot_response = OmnichannelCFOBotGateway.handle_command(
            channel="slack",
            sender_id=sender_id,
            message_text=message_text,
        )

        if settings.slack_bot_token and channel_id:
            slack_msg: dict[str, Any] = {
                "channel": channel_id,
                "text": bot_response.reply_text,
            }
            if bot_response.interactive_blocks:
                slack_msg["blocks"] = bot_response.interactive_blocks

            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(
                    "https://slack.com/api/chat.postMessage",
                    headers={"Authorization": f"Bearer {settings.slack_bot_token}"},
                    json=slack_msg,
                )
        else:
            logger.warning("Slack token not configured. Reply: %s", bot_response.reply_text)

    return {"status": "ok"}
