"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { ChatEvidenceMeta } from "@/components/ui/chat-evidence-chips";

// ── Types ─────────────────────────────────────────────────────────────────────

export type WSChatStatus = "idle" | "connecting" | "connected" | "streaming" | "done" | "error" | "closed";

export interface WSChatMessage {
  role:    "user" | "assistant";
  content: string;
  /** True while the assistant is still streaming tokens */
  streaming?: boolean;
  evidence?: ChatEvidenceMeta;
}

interface SendOptions {
  question: string;
  jobId?:   string | null;
  orgId?:   string | null;
}

interface UseWSChatOptions {
  /** Override the default WS URL. Defaults to auto-detect from window.location */
  url?: string;
  /** Called when a stream completes with the full response text */
  onDone?: (text: string) => void;
  /** Called on error */
  onError?: (msg: string) => void;
}

// ── URL helper ────────────────────────────────────────────────────────────────

function buildWsUrl(path: string): string {
  if (typeof window === "undefined") return "";
  const proto  = window.location.protocol === "https:" ? "wss:" : "ws:";
  const apiBase = process.env.NEXT_PUBLIC_API_URL ?? "";
  if (apiBase) {
    // Strip http/https prefix, replace with ws/wss
    const base = apiBase.replace(/^https?:/, proto);
    return `${base}${path}`;
  }
  return `${proto}//${window.location.host}${path}`;
}

// ── Hook ──────────────────────────────────────────────────────────────────────

/**
 * useWSChat — token-level streaming chat over WebSocket.
 *
 * Usage:
 *   const { messages, status, send, clear } = useWSChat();
 *
 *   // Send a message
 *   send({ question: "Nakit pisti ne kadar?", jobId: activeJobId });
 *
 * DDIA principle: streaming pipeline — process tokens as they arrive,
 * never buffer the full response before rendering.
 */
export function useWSChat(options: UseWSChatOptions = {}) {
  const wsRef     = useRef<WebSocket | null>(null);
  const pingRef   = useRef<ReturnType<typeof setInterval> | null>(null);
  const mountedRef = useRef(true);

  const [messages, setMessages] = useState<WSChatMessage[]>([]);
  const [status,   setStatus]   = useState<WSChatStatus>("idle");
  const [error,    setError]    = useState<string | null>(null);

  // ── Cleanup ──────────────────────────────────────────────────────────────

  const cleanup = useCallback(() => {
    if (pingRef.current) {
      clearInterval(pingRef.current);
      pingRef.current = null;
    }
    if (wsRef.current) {
      wsRef.current.onclose   = null;
      wsRef.current.onerror   = null;
      wsRef.current.onmessage = null;
      if (wsRef.current.readyState === WebSocket.OPEN ||
          wsRef.current.readyState === WebSocket.CONNECTING) {
        wsRef.current.close(1000, "client disconnect");
      }
      wsRef.current = null;
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      cleanup();
    };
  }, [cleanup]);

  // ── Connect ───────────────────────────────────────────────────────────────

  const connect = useCallback((): Promise<WebSocket> => {
    return new Promise((resolve, reject) => {
      cleanup();
      const url = options.url ?? buildWsUrl("/api/v1/ws/chat");
      if (!url) { reject(new Error("No WS URL")); return; }

      setStatus("connecting");
      const ws = new WebSocket(url);
      wsRef.current = ws;

      const timeout = setTimeout(() => {
        ws.close();
        reject(new Error("WebSocket connection timeout"));
      }, 10_000);

      ws.onopen = () => {
        clearTimeout(timeout);
        if (mountedRef.current) setStatus("connected");

        // Keepalive ping every 25 seconds
        pingRef.current = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: "ping" }));
          }
        }, 25_000);

        resolve(ws);
      };

      ws.onerror = () => {
        clearTimeout(timeout);
        reject(new Error("WebSocket connection failed"));
      };

      ws.onclose = (e) => {
        if (mountedRef.current) {
          setStatus(e.wasClean ? "closed" : "error");
          if (!e.wasClean) setError("Bağlantı kesildi");
        }
        if (pingRef.current) clearInterval(pingRef.current);
      };
    });
  }, [cleanup, options.url]);

  // ── Send ──────────────────────────────────────────────────────────────────

  const send = useCallback(async ({ question, jobId, orgId }: SendOptions) => {
    if (!question.trim()) return;

    // Add user message to history
    setMessages((prev) => [...prev, { role: "user", content: question }]);
    setError(null);

    // Get or create WS connection
    let ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      try {
        ws = await connect();
      } catch (err) {
        const msg = err instanceof Error ? err.message : "Bağlantı hatası";
        setError(msg);
        setStatus("error");
        options.onError?.(msg);
        return;
      }
    }

    // Append streaming assistant placeholder
    setMessages((prev) => [
      ...prev,
      { role: "assistant", content: "", streaming: true },
    ]);
    setStatus("streaming");

    // Send chat message
    ws.send(JSON.stringify({
      type:     "chat",
      question,
      job_id:   jobId  ?? undefined,
      org_id:   orgId  ?? undefined,
    }));

    // Handle incoming messages for this stream
    ws.onmessage = (event: MessageEvent) => {
      if (!mountedRef.current) return;
      try {
        const data = JSON.parse(event.data as string) as {
          type:       string;
          content?:   string;
          full_text?: string;
          message?:   string;
          evidence_found?: boolean;
          evidence_tx_count?: number;
          evidence_semantic_count?: number;
          evidence_retriever_version?: string;
          grounding_validated?: boolean;
        };

        switch (data.type) {
          case "token":
            // Append token to last assistant message
            setMessages((prev) => {
              const updated = [...prev];
              const last = updated[updated.length - 1];
              if (last?.role === "assistant") {
                updated[updated.length - 1] = {
                  ...last,
                  content:   last.content + (data.content ?? ""),
                  streaming: true,
                };
              }
              return updated;
            });
            break;

          case "done":
            // Finalise the streaming message
            setMessages((prev) => {
              const updated = [...prev];
              const last = updated[updated.length - 1];
              if (last?.role === "assistant") {
                updated[updated.length - 1] = {
                  ...last,
                  content:   data.full_text ?? last.content,
                  streaming: false,
                  evidence: {
                    evidence_found: data.evidence_found,
                    evidence_tx_count: data.evidence_tx_count,
                    evidence_semantic_count: data.evidence_semantic_count,
                    evidence_retriever_version: data.evidence_retriever_version,
                    grounding_validated: data.grounding_validated,
                  },
                };
              }
              return updated;
            });
            setStatus("done");
            options.onDone?.(data.full_text ?? "");
            // Ready for next message
            setTimeout(() => {
              if (mountedRef.current) setStatus("connected");
            }, 200);
            break;

          case "error":
            setMessages((prev) => {
              const updated = [...prev];
              const last = updated[updated.length - 1];
              if (last?.role === "assistant") {
                updated[updated.length - 1] = {
                  role:      "assistant",
                  content:   `[Hata: ${data.message ?? "Bilinmeyen hata"}]`,
                  streaming: false,
                };
              }
              return updated;
            });
            setStatus("error");
            setError(data.message ?? "Bilinmeyen hata");
            options.onError?.(data.message ?? "Bilinmeyen hata");
            break;

          case "status":
            // Optional: show status in UI (ignored here, caller can handle)
            break;

          case "pong":
            break;
        }
      } catch {
        // Ignore parse errors
      }
    };
  }, [connect, options]);

  // ── Clear ─────────────────────────────────────────────────────────────────

  const clear = useCallback(() => {
    setMessages([]);
    setStatus(wsRef.current?.readyState === WebSocket.OPEN ? "connected" : "idle");
    setError(null);
  }, []);

  // ── Disconnect ────────────────────────────────────────────────────────────

  const disconnect = useCallback(() => {
    cleanup();
    if (mountedRef.current) setStatus("closed");
  }, [cleanup]);

  return {
    messages,
    status,
    error,
    isStreaming: status === "streaming",
    isConnected: status === "connected" || status === "streaming" || status === "done",
    send,
    clear,
    disconnect,
  };
}
