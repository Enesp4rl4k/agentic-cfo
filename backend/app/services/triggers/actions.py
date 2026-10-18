"""The P4-1 action registry — what a trigger does once its condition holds.

Each ``ActionKind`` from ``contracts.py`` maps to an async handler:

    handler(db, org_id, definition, payload) -> dict

Handlers validate their own ``action_params`` (deliberate layering — the
envelope stays free-form in the contract) and persist their side effects. Only
``alert.dispatch`` lands in P4-1; the other kinds arrive in P4-2, and an
unregistered kind is reported as an ``error`` run rather than silently doing
nothing.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert_rule import AlertHistory
from app.services.triggers.contracts import TriggerDefinition

logger = logging.getLogger(__name__)

# db, org_id, definition, event payload -> JSON-serialisable action result
ActionHandler = Callable[
    [AsyncSession, str, TriggerDefinition, dict[str, Any]], Awaitable[dict[str, Any]]
]


async def _alert_dispatch(
    db: AsyncSession,
    org_id: str,
    definition: TriggerDefinition,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Write a durable alert (``alert_history``) and optionally fan it out.

    The alert is always recorded so the trigger's effect is auditable. If the
    params carry a ``webhook_url`` the alert is also delivered best-effort via
    the existing ``AlertDispatcher``; delivery failure is reported in the result
    but never fails the run (the alert is already persisted).
    """
    params = definition.action_params
    message = str(
        params.get("message")
        or payload.get("message")
        or f"Trigger '{definition.name}' fired"
    )
    severity = str(params.get("severity") or "warning")
    channels = params.get("channels") or []

    alert = AlertHistory(
        org_id=org_id,
        message=message,
        severity=severity,
        source=f"trigger:{definition.name}",
        channels_sent=json.dumps(channels) if channels else None,
    )
    db.add(alert)
    await db.flush()

    result: dict[str, Any] = {
        "alert_id": alert.id,
        "severity": severity,
        "message": message,
        "channels": channels,
        "delivered": False,
    }

    webhook_url = params.get("webhook_url")
    if webhook_url:
        try:
            from app.services.alert_dispatcher import AlertDispatcher

            dispatched = await AlertDispatcher.dispatch_webhook(
                webhook_url,
                event_type="trigger.alert",
                data={"alert_id": alert.id, "message": message, "severity": severity},
            )
            result["delivered"] = bool(dispatched.delivered)
            result["delivery_status"] = dispatched.status_code
        except Exception as exc:  # pragma: no cover - network best-effort
            logger.warning("trigger alert webhook delivery failed: %s", exc)
            result["delivered"] = False
            result["delivery_error"] = str(exc)

    return result


ACTION_REGISTRY: dict[str, ActionHandler] = {
    "alert.dispatch": _alert_dispatch,
}
