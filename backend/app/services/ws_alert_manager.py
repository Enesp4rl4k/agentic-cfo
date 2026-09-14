"""
WSAlertManager — WebSocket org-channel broadcast service (Sprint M1).

Architecture
------------
Mevcut SSE: job-scoped (pipeline progress için çalışıyor)
Bu servis: org-scoped (alert push) — farklı amaç, paralel çalışır.

Connection lifecycle:
  ws://api/v1/ws/alerts/{org_id}?token={jwt}
  → connect → join org channel → receive alerts in real-time
  → disconnect → leave org channel

Message format (outbound):
  { "type": "new_alert",             "alert": {...},    "ts": "..." }
  { "type": "alert_acknowledged",    "alert_id": "...", "by": "..." }
  { "type": "heartbeat",             "ts": "..." }

Concurrency:
  - asyncio.Lock per org channel for safe broadcast
  - Stale connections detected by write failure → auto-remove

Usage:
    manager = get_ws_alert_manager()
    await manager.connect(org_id, websocket)
    await manager.broadcast_alert(org_id, alert_dict)
    await manager.disconnect(org_id, websocket)
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


# ── Types ──────────────────────────────────────────────────────────────────────

try:
    from fastapi import WebSocket as _WebSocket
    WebSocket = _WebSocket
except ImportError:
    WebSocket = Any  # type: ignore[assignment]


# ── WSAlertManager ────────────────────────────────────────────────────────────

class WSAlertManager:
    """
    Org-scoped WebSocket broadcast manager.

    One channel per org_id — all users in the same org share the channel.
    Thread/task-safe: uses asyncio.Lock per channel.
    """

    def __init__(self) -> None:
        # org_id → set of active WebSocket connections
        self._connections: dict[str, set[Any]] = {}
        # org_id → asyncio.Lock for safe broadcast
        self._locks: dict[str, asyncio.Lock] = {}

    def _get_lock(self, org_id: str) -> asyncio.Lock:
        if org_id not in self._locks:
            self._locks[org_id] = asyncio.Lock()
        return self._locks[org_id]

    async def connect(self, org_id: str, ws: Any) -> None:
        """Accept a new WebSocket connection and add to org channel."""
        await ws.accept()
        if org_id not in self._connections:
            self._connections[org_id] = set()
        self._connections[org_id].add(ws)
        logger.debug("WSAlerts: connected org=%s total=%d", org_id, len(self._connections[org_id]))

        # Send welcome heartbeat
        try:
            await ws.send_text(json.dumps({
                "type":    "connected",
                "org_id":  org_id,
                "message": "Real-time alert channel hazır",
                "ts":      datetime.now(UTC).isoformat(),
            }))
        except Exception:
            pass

    async def disconnect(self, org_id: str, ws: Any) -> None:
        """Remove a WebSocket from the org channel."""
        if org_id in self._connections:
            self._connections[org_id].discard(ws)
            if not self._connections[org_id]:
                del self._connections[org_id]
                self._locks.pop(org_id, None)
        logger.debug("WSAlerts: disconnected org=%s", org_id)

    def connection_count(self, org_id: str) -> int:
        return len(self._connections.get(org_id, set()))

    def total_connections(self) -> int:
        return sum(len(c) for c in self._connections.values())

    async def broadcast_alert(self, org_id: str, alert: dict[str, Any]) -> None:
        """
        Broadcast a new alert to all connections in the org channel.
        Stale/closed connections are automatically removed.
        """
        if org_id not in self._connections:
            return

        message = json.dumps({
            "type":  "new_alert",
            "alert": alert,
            "ts":    datetime.now(UTC).isoformat(),
        })

        await self._broadcast(org_id, message)

    async def broadcast_acknowledgement(
        self,
        org_id:   str,
        alert_id: str,
        by_user:  str,
    ) -> None:
        """
        Broadcast alert acknowledgement to all org members.
        Ensures all users see the alert as acknowledged in real-time.
        """
        message = json.dumps({
            "type":     "alert_acknowledged",
            "alert_id": alert_id,
            "by":       by_user,
            "ts":       datetime.now(UTC).isoformat(),
        })
        await self._broadcast(org_id, message)

    async def send_heartbeat(self, org_id: str) -> None:
        """Send a heartbeat ping to keep connections alive."""
        message = json.dumps({
            "type": "heartbeat",
            "ts":   datetime.now(UTC).isoformat(),
        })
        await self._broadcast(org_id, message)

    async def _broadcast(self, org_id: str, message: str) -> None:
        """
        Send message to all connections in an org channel.
        Removes stale connections on failure.
        """
        conns = self._connections.get(org_id, set())
        if not conns:
            return

        # Copy snapshot to avoid modification during iteration
        snapshot = list(conns)
        stale: list[Any] = []

        lock = self._get_lock(org_id)
        async with lock:
            for ws in snapshot:
                try:
                    await ws.send_text(message)
                except Exception:
                    stale.append(ws)

        # Remove stale connections outside lock
        for ws in stale:
            conns.discard(ws)
            logger.debug("WSAlerts: removed stale connection from org=%s", org_id)


# ── Singleton ─────────────────────────────────────────────────────────────────

_manager: WSAlertManager | None = None


def get_ws_alert_manager() -> WSAlertManager:
    """Return the singleton WSAlertManager."""
    global _manager
    if _manager is None:
        _manager = WSAlertManager()
    return _manager
