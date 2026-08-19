"""
WebSocket Alerts API — Sprint M1

WebSocket endpoint for real-time org-scoped alert delivery.

ws://api/v1/ws/alerts/{org_id}?token={jwt}

Message types (server → client):
  connected:            Initial welcome + channel info
  new_alert:            A new alert has been dispatched
  alert_acknowledged:   Another user acknowledged an alert
  heartbeat:            Keep-alive ping (every 20s)

REST endpoints:
  GET  /alerts/history/{org_id}       → Persistent alert history (DB)
  PATCH /alerts/{alert_id}/acknowledge → Mark alert as acknowledged
  POST /alerts/channels/test           → Send test alert to channel
  GET  /alerts/rules                   → List alert rules for org
  POST /alerts/rules                   → Create alert rule
  DELETE /alerts/rules/{rule_id}       → Delete alert rule
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.models.user import User

router = APIRouter(tags=["ws-alerts"])
logger = logging.getLogger(__name__)


# ── Request schemas ───────────────────────────────────────────────────────────

class AlertRuleCreate(BaseModel):
    name:      str
    metric:    str        # "cash_runway_months" | "anomaly_count_critical" | ...
    operator:  str        # "<" | ">" | "==" | ">="
    threshold: float
    channels:  list[str] = ["in_app"]
    severity:  str = "warning"
    enabled:   bool = True


class AcknowledgeRequest(BaseModel):
    note: str = ""


# ── WebSocket endpoint ────────────────────────────────────────────────────────

@router.websocket("/ws/alerts/{org_id}")
async def ws_alerts(
    org_id:  str,
    ws:      WebSocket,
    token:   str | None = Query(None),   # JWT via query param
) -> None:
    """
    Org-scoped WebSocket alert channel.

    Authentication: pass JWT as ?token=<jwt> query parameter.
    Once connected, the client receives real-time alerts for the org.

    Client does not need to send any messages — read-only channel.
    If client sends an "ack" message, it will be broadcast to all org members.

    Example client (JavaScript):
        const ws = new WebSocket(`${WS_BASE}/ws/alerts/${orgId}?token=${jwt}`);
        ws.onmessage = (e) => {
          const msg = JSON.parse(e.data);
          if (msg.type === 'new_alert') dispatch(addAlert(msg.alert));
        };
    """
    from app.services.ws_alert_manager import get_ws_alert_manager
    import asyncio

    # Auth: validate JWT token
    if token:
        try:
            from app.services.auth import decode_token
            payload = decode_token(token)
            user_id = payload.get("sub", "unknown")
        except Exception:
            await ws.close(code=4001, reason="Invalid token")
            return
    else:
        # No token — allow in dev/demo mode but log warning
        logger.warning("WSAlerts: unauthenticated connection for org=%s", org_id)
        user_id = "anonymous"

    manager = get_ws_alert_manager()
    await manager.connect(org_id, ws)

    # Heartbeat task
    heartbeat_task: asyncio.Task | None = None

    async def _heartbeat() -> None:
        while True:
            await asyncio.sleep(20)
            try:
                await manager.send_heartbeat(org_id)
            except Exception:
                break

    try:
        heartbeat_task = asyncio.create_task(_heartbeat())

        # Listen for client messages (ack, ping)
        while True:
            try:
                raw = await ws.receive_text()
                msg = json.loads(raw)

                if msg.get("type") == "ack" and msg.get("alert_id"):
                    await manager.broadcast_acknowledgement(
                        org_id   = org_id,
                        alert_id = msg["alert_id"],
                        by_user  = user_id,
                    )
                elif msg.get("type") == "ping":
                    await ws.send_text(json.dumps({"type": "pong", "ts": datetime.now(timezone.utc).isoformat()}))

            except WebSocketDisconnect:
                break
            except Exception as exc:
                logger.debug("WSAlerts: receive error: %s", exc)
                break

    finally:
        if heartbeat_task:
            heartbeat_task.cancel()
        await manager.disconnect(org_id, ws)
        logger.debug("WSAlerts: disconnected user=%s org=%s", user_id, org_id)


# ── Alert history (DB-backed) ─────────────────────────────────────────────────

@router.get("/alerts/history/{org_id}")
async def alert_history(
    org_id:       str,
    severity:     str | None = None,
    days:         int = 7,
    acknowledged: bool | None = None,
    user:         User = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Persistent alert history from DB.
    Replaces Redis TTL-based storage — alerts are kept forever.
    """
    try:
        from sqlalchemy import text
        from datetime import timedelta

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        query  = (
            "SELECT id, message, severity, source, channels_sent, "
            "acknowledged, acknowledged_by, acknowledged_at, created_at "
            "FROM alert_history "
            "WHERE org_id = :org_id AND created_at >= :cutoff"
        )
        params: dict[str, Any] = {"org_id": org_id, "cutoff": cutoff}

        if severity:
            query += " AND severity = :severity"
            params["severity"] = severity

        if acknowledged is not None:
            query += " AND acknowledged = :acked"
            params["acked"] = acknowledged

        query += " ORDER BY created_at DESC LIMIT 200"

        result = await db.execute(text(query), params)
        rows   = result.fetchall()

        alerts = [
            {
                "id":              row[0],
                "message":         row[1],
                "severity":        row[2],
                "source":          row[3],
                "channels_sent":   row[4],
                "acknowledged":    row[5],
                "acknowledged_by": row[6],
                "acknowledged_at": row[7].isoformat() if row[7] else None,
                "created_at":      row[8].isoformat() if row[8] else None,
            }
            for row in rows
        ]

        return {
            "data":  {"org_id": org_id, "alerts": alerts, "count": len(alerts)},
            "error": None,
        }

    except Exception as exc:
        logger.warning("Alert history failed for org=%s: %s", org_id, exc)
        return {"data": {"org_id": org_id, "alerts": [], "count": 0}, "error": None}


# ── Acknowledge endpoint ──────────────────────────────────────────────────────

@router.patch("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(
    alert_id: str,
    body:     AcknowledgeRequest,
    user:     User = Depends(get_current_user),
    db:       AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Acknowledge an alert. Broadcasts to all org WS connections.
    """
    from app.services.ws_alert_manager import get_ws_alert_manager

    try:
        from sqlalchemy import text

        # Update DB
        await db.execute(
            text(
                "UPDATE alert_history "
                "SET acknowledged = true, "
                "    acknowledged_by = :user_id, "
                "    acknowledged_at = :now "
                "WHERE id = :id"
            ),
            {
                "user_id": str(user.id),
                "now":     datetime.now(timezone.utc),
                "id":      alert_id,
            },
        )
        await db.commit()
    except Exception as exc:
        logger.warning("Alert acknowledge DB update failed: %s", exc)

    # Also broadcast to in-app notifications
    org_id = str(user.org_id) if user.org_id else None
    if org_id:
        manager = get_ws_alert_manager()
        await manager.broadcast_acknowledgement(
            org_id   = org_id,
            alert_id = alert_id,
            by_user  = str(user.id),
        )

    return {
        "data": {
            "alert_id":       alert_id,
            "acknowledged":   True,
            "acknowledged_by": str(user.id),
        },
        "error": None,
    }


# ── Test channel endpoint ─────────────────────────────────────────────────────

@router.post("/alerts/channels/test")
async def test_alert_channel(
    channel:     str = "in_app",
    destination: str | None = None,
    user:        User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Send a test alert to verify channel configuration.
    channel: "in_app" | "slack" | "email" | "whatsapp"
    """
    from app.services.ws_alert_manager import get_ws_alert_manager

    org_id = str(user.org_id) if user.org_id else None
    if not org_id:
        raise HTTPException(status_code=400, detail="Organizasyona üye değilsiniz.")

    test_alert = {
        "id":       "test-alert",
        "message":  "✅ Test alert — kanal bağlantısı başarılı",
        "severity": "info",
        "source":   "test",
        "ts":       datetime.now(timezone.utc).isoformat(),
    }

    if channel == "in_app":
        manager = get_ws_alert_manager()
        conn_count = manager.connection_count(org_id)
        if conn_count > 0:
            await manager.broadcast_alert(org_id, test_alert)

        return {
            "data": {
                "channel":     "in_app",
                "sent":        conn_count > 0,
                "connections": conn_count,
                "message":     f"{conn_count} aktif bağlantıya gönderildi",
            },
            "error": None,
        }

    elif channel == "slack":
        # Use existing NotificationService
        try:
            from app.services.notification_service import NotificationService
            from app.services.alert_router import RawAlert, AlertRouter

            alert = RawAlert(
                level="info", message="Test alert — Slack kanal testi",
                domain="system", source="test", job_id="test",
            )
            router_svc = AlertRouter(escalate_threshold=0.9)
            decisions  = router_svc.process_alerts([alert])
            svc = NotificationService()
            result = await svc.deliver(decisions, org_id=org_id, org_name="Test")
            return {"data": {"channel": "slack", "result": result}, "error": None}
        except Exception as exc:
            return {"data": {"channel": "slack", "sent": False, "error": str(exc)}, "error": None}

    return {
        "data": {"channel": channel, "sent": False, "message": "Kanal desteklenmiyor"},
        "error": None,
    }


# ── Alert rules ───────────────────────────────────────────────────────────────

@router.get("/alerts/rules")
async def list_alert_rules(
    user: User = Depends(get_current_user),
    db:   AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List custom alert rules for the org."""
    org_id = str(user.org_id) if user.org_id else None
    if not org_id:
        raise HTTPException(status_code=400, detail="Organizasyona üye değilsiniz.")

    try:
        from sqlalchemy import text
        result = await db.execute(
            text("SELECT id, name, metric, operator, threshold, channels, severity, enabled, created_at "
                 "FROM alert_rules WHERE org_id = :org_id ORDER BY created_at DESC"),
            {"org_id": org_id},
        )
        rows = result.fetchall()
        rules = [
            {
                "id":        row[0],
                "name":      row[1],
                "metric":    row[2],
                "operator":  row[3],
                "threshold": row[4],
                "channels":  row[5],
                "severity":  row[6],
                "enabled":   row[7],
                "created_at": row[8].isoformat() if row[8] else None,
            }
            for row in rows
        ]
        return {"data": {"org_id": org_id, "rules": rules, "count": len(rules)}, "error": None}
    except Exception:
        return {"data": {"org_id": org_id, "rules": [], "count": 0}, "error": None}


@router.post("/alerts/rules")
async def create_alert_rule(
    body: AlertRuleCreate,
    user: User = Depends(get_current_user),
    db:   AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Create a custom alert rule."""
    org_id = str(user.org_id) if user.org_id else None
    if not org_id:
        raise HTTPException(status_code=400, detail="Organizasyona üye değilsiniz.")

    import uuid as _uuid
    rule_id = _uuid.uuid4().hex

    try:
        from sqlalchemy import text
        await db.execute(
            text(
                "INSERT INTO alert_rules (id, org_id, name, metric, operator, threshold, "
                "channels, severity, enabled, created_at) "
                "VALUES (:id, :org_id, :name, :metric, :op, :threshold, "
                ":channels, :severity, :enabled, :now)"
            ),
            {
                "id":        rule_id,
                "org_id":    org_id,
                "name":      body.name,
                "metric":    body.metric,
                "op":        body.operator,
                "threshold": body.threshold,
                "channels":  json.dumps(body.channels),
                "severity":  body.severity,
                "enabled":   body.enabled,
                "now":       datetime.now(timezone.utc),
            },
        )
        await db.commit()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {
        "data": {"rule_id": rule_id, "name": body.name, "created": True},
        "error": None,
    }


@router.delete("/alerts/rules/{rule_id}")
async def delete_alert_rule(
    rule_id: str,
    user:    User = Depends(get_current_user),
    db:      AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Delete an alert rule."""
    try:
        from sqlalchemy import text
        await db.execute(text("DELETE FROM alert_rules WHERE id = :id"), {"id": rule_id})
        await db.commit()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"data": {"rule_id": rule_id, "deleted": True}, "error": None}
