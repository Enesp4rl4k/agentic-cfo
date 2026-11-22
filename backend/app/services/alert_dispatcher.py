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

from app.core import outbound

logger = logging.getLogger(__name__)


def _transport_reason(exc: Exception) -> str:
    """A word for the delivery status ("timeout", "connection_failed"), never the exception text."""
    if isinstance(exc, httpx.TimeoutException | TimeoutError):
        return "timeout"
    if isinstance(exc, httpx.TransportError):
        return "connection_failed"
    return ""


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
    blocked_reason: str = ""  # set when the destination was refused and nothing was sent


class AlertDispatcher:
    """Dispatches financial warnings across communication channels.

    A delivery is reported only when an HTTP endpoint answered. Tests that must not
    reach the network inject `transport` (an `httpx.MockTransport`); nothing in the
    application sets it, and it is refused outside a pytest run, so a URL can never be
    "delivered" without a request having been made.
    """

    transport: httpx.AsyncBaseTransport | None = None

    @classmethod
    def test_transport_injected(cls) -> bool:
        """Whether a test has injected a transport (so a send goes to it, never to the network)."""
        return cls.transport is not None

    @classmethod
    async def _post(cls, url: str, payload: dict[str, Any]) -> outbound.OutboundResponse:
        """The only way this class sends: through the guarded client (app/core/outbound.py)."""
        return await outbound.request("POST", url, json=payload, transport=cls.transport)

    @staticmethod
    def _blocked(channel: str, url: str, severity: str, title: str, reason: str, ts: str) -> DispatchedAlert:
        return DispatchedAlert(
            alert_id=f"alert-{channel}-{int(datetime.now().timestamp())}", channel=channel, target=url,
            severity=severity, title=title, message=f"Destination refused: {reason}",
            delivered=False, status_code=0, timestamp=ts, blocked_reason=reason,
        )

    @staticmethod
    def _not_configured(channel: str, severity: str, title: str, message: str) -> DispatchedAlert:
        """No destination: nothing was sent, and the result says so."""
        return DispatchedAlert(
            alert_id=f"alert-{channel}-{int(datetime.now().timestamp())}",
            channel=channel, target="", severity=severity, title=title, message=message,
            delivered=False, status_code=0, timestamp=datetime.now(UTC).isoformat(),
        )

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

        if not webhook_url:
            return cls._not_configured("slack", severity, title, message)

        try:
            resp = await cls._post(webhook_url, payload)
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
        except outbound.OutboundBlocked as blocked:
            return cls._blocked("slack", webhook_url, severity, title, blocked.reason, ts)
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
                blocked_reason=_transport_reason(exc),
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

        if not webhook_url:
            return cls._not_configured(
                "webhook", data.get("severity", "info"), f"Webhook: {event_type}",
                f"Event {event_type} not sent: no URL",
            )

        try:
            resp = await cls._post(webhook_url, payload)
            return DispatchedAlert(
                alert_id=f"alert-wh-{int(datetime.now().timestamp())}",
                channel="webhook",
                target=webhook_url,
                severity=data.get("severity", "info"),
                title=f"Webhook: {event_type}",
                message=f"Event {event_type} dispatched",
                delivered=resp.ok,
                status_code=resp.status_code,
                timestamp=ts,
            )
        except outbound.OutboundBlocked as blocked:
            return cls._blocked(
                "webhook", webhook_url, data.get("severity", "info"), f"Webhook: {event_type}",
                blocked.reason, ts,
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
                blocked_reason=_transport_reason(exc),
            )
