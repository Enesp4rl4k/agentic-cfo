"use client";

/**
 * useAlertWebSocket — Real-time org-scoped WebSocket alert hook (Sprint M1)
 *
 * Connects to ws://api/v1/ws/alerts/{orgId}?token={jwt}
 * Receives: new_alert | alert_acknowledged | heartbeat | connected
 * Sends:    ack { type: "ack", alert_id } | ping
 *
 * Features:
 *  - Exponential backoff reconnect: 1s → 2s → 4s → 8s → 16s → max 30s
 *  - Heartbeat ping every 20s (server sends, client just monitors)
 *  - Alert ring buffer: max 50, oldest dropped on overflow
 *  - unreadCount: increments on new_alert, resets on acknowledgeAlert
 *  - Automatic cleanup on unmount
 *
 * Usage:
 *   const { alerts, unreadCount, status, acknowledgeAlert } = useAlertWebSocket(orgId);
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useSession } from "next-auth/react";

// ── Types ──────────────────────────────────────────────────────────────────────

export type WSAlertStatus = "idle" | "connecting" | "connected" | "error" | "closed";

export interface AlertMessage {
  id:              string;
  message:         string;
  severity:        "critical" | "high" | "warning" | "info";
  source?:         string;
  acknowledged?:   boolean;
  acknowledged_by?: string;
  ts:              string;
}

interface WSMessage {
  type:            string;
  alert?:          AlertMessage;
  alert_id?:       string;
  by?:             string;
  ts?:             string;
  org_id?:         string;
  message?:        string;
}

interface UseAlertWebSocketReturn {
  status:           WSAlertStatus;
  alerts:           AlertMessage[];    // ring buffer, max 50
  unreadCount:      number;
  acknowledgeAlert: (alertId: string) => void;
  clearAll:         () => void;
}

// ── Constants ─────────────────────────────────────────────────────────────────

const MAX_ALERTS    = 50;
const MAX_BACKOFF   = 30_000;   // 30s max reconnect delay
const INITIAL_DELAY = 1_000;    // 1s initial backoff

function getWsBase(): string {
  if (typeof window === "undefined") return "";
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  const host  = process.env.NEXT_PUBLIC_API_URL?.replace(/^https?:\/\//, "") ||
                window.location.host;
  return `${proto}//${host}/api/v1`;
}

// ── Hook ───────────────────────────────────────────────────────────────────────

export function useAlertWebSocket(orgId: string | null | undefined): UseAlertWebSocketReturn {
  const { data: session } = useSession();
  const token = (session as { accessToken?: string } | null)?.accessToken;

  const [status, setStatus]       = useState<WSAlertStatus>("idle");
  const [alerts, setAlerts]       = useState<AlertMessage[]>([]);
  const [unreadCount, setUnread]  = useState(0);

  const wsRef         = useRef<WebSocket | null>(null);
  const retryCount    = useRef(0);
  const retryTimer    = useRef<NodeJS.Timeout | null>(null);
  const mountedRef    = useRef(true);

  const cleanup = useCallback(() => {
    if (retryTimer.current) {
      clearTimeout(retryTimer.current);
      retryTimer.current = null;
    }
    if (wsRef.current) {
      wsRef.current.onclose   = null;
      wsRef.current.onerror   = null;
      wsRef.current.onmessage = null;
      wsRef.current.onopen    = null;
      if (wsRef.current.readyState === WebSocket.OPEN ||
          wsRef.current.readyState === WebSocket.CONNECTING) {
        wsRef.current.close(1000, "component unmounting");
      }
      wsRef.current = null;
    }
  }, []);

  const connect = useCallback(() => {
    if (!orgId || !mountedRef.current) return;

    const base = getWsBase();
    if (!base) return;

    const url = token
      ? `${base}/ws/alerts/${orgId}?token=${encodeURIComponent(token)}`
      : `${base}/ws/alerts/${orgId}`;

    cleanup();
    setStatus("connecting");

    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      if (!mountedRef.current) return;
      retryCount.current = 0;
      setStatus("connected");
    };

    ws.onmessage = (event) => {
      if (!mountedRef.current) return;
      try {
        const msg: WSMessage = JSON.parse(event.data as string);

        if (msg.type === "new_alert" && msg.alert) {
          setAlerts((prev) => {
            const next = [msg.alert!, ...prev];
            return next.slice(0, MAX_ALERTS);  // ring buffer
          });
          setUnread((n) => n + 1);
        }

        if (msg.type === "alert_acknowledged" && msg.alert_id) {
          setAlerts((prev) =>
            prev.map((a) =>
              a.id === msg.alert_id
                ? { ...a, acknowledged: true, acknowledged_by: msg.by }
                : a
            )
          );
        }

        // heartbeat / connected: no-op (server manages keepalive)

      } catch {
        // Ignore malformed messages
      }
    };

    ws.onclose = (event) => {
      if (!mountedRef.current) return;
      setStatus(event.wasClean ? "closed" : "error");

      // Don't reconnect on clean close
      if (event.wasClean || event.code === 4001) return;

      // Exponential backoff
      const delay = Math.min(
        INITIAL_DELAY * Math.pow(2, retryCount.current),
        MAX_BACKOFF,
      );
      retryCount.current += 1;

      retryTimer.current = setTimeout(() => {
        if (mountedRef.current) connect();
      }, delay);
    };

    ws.onerror = () => {
      if (!mountedRef.current) return;
      setStatus("error");
    };
  }, [orgId, token, cleanup]);

  // Connect on mount / orgId change
  useEffect(() => {
    mountedRef.current = true;

    if (orgId) {
      connect();
    }

    return () => {
      mountedRef.current = false;
      cleanup();
    };
  }, [orgId, connect, cleanup]);

  // Reconnect when token changes (e.g. refresh)
  useEffect(() => {
    if (orgId && token && status === "closed") {
      retryCount.current = 0;
      connect();
    }
  }, [token, orgId, status, connect]);

  const acknowledgeAlert = useCallback((alertId: string) => {
    // Optimistic update
    setAlerts((prev) =>
      prev.map((a) => (a.id === alertId ? { ...a, acknowledged: true } : a))
    );
    setUnread((n) => Math.max(0, n - 1));

    // Send ack over WS so other users see it in real-time
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "ack", alert_id: alertId }));
    }
  }, []);

  const clearAll = useCallback(() => {
    setAlerts([]);
    setUnread(0);
  }, []);

  return { status, alerts, unreadCount, acknowledgeAlert, clearAll };
}
