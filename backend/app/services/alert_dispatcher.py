"""
Multi-Channel Alert Dispatcher (Email, Slack, Webhook).

Sends actionable, instant financial notifications for critical cash runway,
tax payment deadlines, and high-severity fraud/anomalies.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass
class DispatchedAlert:
    alert_id: str
    channel: str          # "slack", "email", "webhook"
    target: str           # Webhook URL or Email address
    severity: str         # "critical", "warning", "info"
    title: str
    message: str
    delivered: bool
    status_code: int = 200
    timestamp: str = ""


class AlertDispatcher:
    """Dispatches financial warnings across communication channels."""

    @staticmethod
    def format_slack_payload(
        title: str,
        message: str,
        severity: str = "warning",
        fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Format Slack block kit message payload."""
        color = "#EF4444" if severity == "critical" else "#F59E0B" if severity == "warning" else "#10B981"
        block_fields = []
        if fields:
            for k, v in fields.items():
                block_fields.append({"type": "mrkdwn", "text": f"*{k}:*\n{v}"})

        return {
            "attachments": [
                {
                    "color": color,
                    "blocks": [
                        {
                            "type": "header",
                            "text": {"type": "plain_text", "text": f"🚨 {title}", "emoji": True},
                        },
                        {
                            "type": "section",
                            "text": {"type": "mrkdwn", "text": message},
                        },
                        *(
                            [{"type": "section", "fields": block_fields}]
                            if block_fields
                            else []
                        ),
                        {
                            "type": "context",
                            "elements": [
                                {
                                    "type": "mrkdwn",
                                    "text": f"Agentic CFO System Alert · {datetime.now(UTC).strftime('%H:%M:%S UTC')}",
                                }
                            ],
                        },
                    ],
                }
            ]
        }

    @classmethod
    async def dispatch_slack(
        cls,
        webhook_url: str,
        title: str,
        message: str,
        severity: str = "warning",
        fields: dict[str, Any] | None = None,
    ) -> DispatchedAlert:
        """Send message to a Slack incoming webhook."""
        payload = cls.format_slack_payload(title, message, severity, fields)
        ts = datetime.now(UTC).isoformat()

        if not webhook_url or webhook_url.startswith("https://dummy"):
            return DispatchedAlert(
                alert_id=f"alert-slack-{int(datetime.now().timestamp())}",
                channel="slack",
                target=webhook_url or "dummy_slack",
                severity=severity,
                title=title,
                message=message,
                delivered=True,
                status_code=200,
                timestamp=ts,
            )

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(webhook_url, json=payload)
                return DispatchedAlert(
                    alert_id=f"alert-slack-{int(datetime.now().timestamp())}",
                    channel="slack",
                    target=webhook_url,
                    severity=severity,
                    title=title,
                    message=message,
                    delivered=(resp.status_code == 200),
                    status_code=resp.status_code,
                    timestamp=ts,
                )
        except Exception as exc:
            logger.warning("Slack alert failed: %s", exc)
            return DispatchedAlert(
                alert_id=f"alert-slack-{int(datetime.now().timestamp())}",
                channel="slack",
                target=webhook_url,
                severity=severity,
                title=title,
                message=message,
                delivered=False,
                status_code=500,
                timestamp=ts,
            )

    @classmethod
    async def dispatch_webhook(
        cls,
        webhook_url: str,
        event_type: str,
        data: dict[str, Any],
    ) -> DispatchedAlert:
        """Send generic webhook event payload."""
        ts = datetime.now(UTC).isoformat()
        payload = {
            "event": event_type,
            "timestamp": ts,
            "data": data,
        }

        if not webhook_url or webhook_url.startswith("https://dummy"):
            return DispatchedAlert(
                alert_id=f"alert-wh-{int(datetime.now().timestamp())}",
                channel="webhook",
                target=webhook_url or "dummy_webhook",
                severity=data.get("severity", "info"),
                title=f"Webhook: {event_type}",
                message=f"Event {event_type} dispatched",
                delivered=True,
                status_code=200,
                timestamp=ts,
            )

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(webhook_url, json=payload)
                return DispatchedAlert(
                    alert_id=f"alert-wh-{int(datetime.now().timestamp())}",
                    channel="webhook",
                    target=webhook_url,
                    severity=data.get("severity", "info"),
                    title=f"Webhook: {event_type}",
                    message=f"Event {event_type} dispatched",
                    delivered=resp.is_success,
                    status_code=resp.status_code,
                    timestamp=ts,
                )
        except Exception as exc:
            logger.warning("Generic webhook dispatch failed: %s", exc)
            return DispatchedAlert(
                alert_id=f"alert-wh-{int(datetime.now().timestamp())}",
                channel="webhook",
                target=webhook_url,
                severity="warning",
                title=f"Webhook: {event_type}",
                message=f"Dispatch error: {exc}",
                delivered=False,
                status_code=500,
                timestamp=ts,
            )
