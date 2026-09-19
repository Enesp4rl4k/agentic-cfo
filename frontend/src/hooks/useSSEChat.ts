"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiClient } from "@/lib/api/client";

// ── Types ─────────────────────────────────────────────────────────────────────

export type SSEChatStatus = "idle" | "connecting" | "streaming" | "done" | "error";

export interface SSEChatMessage {
  role: "user" | "assistant";
  content: string;
  streaming?: boolean;
}

interface SendOptions {
  question: string;
  jobId?: string | null;
  orgId?: string | null;
}

interface UseSSEChatOptions {
  onDone?: (text: string) => void;
  onError?: (msg: string) => void;
}

// ── Hook ──────────────────────────────────────────────────────────────────────

/**
 * useSSEChat — token-level streaming chat over Server-Sent Events (SSE).
 * Fallback when WebSocket is not available.
 *
 * Usage:
 *   const { messages, status, send, clear } = useSSEChat();
 *   send({ question: "Nakit pisti ne kadar?", jobId: activeJobId });
 */
export function useSSEChat(options: UseSSEChatOptions = {}) {
  const eventSourceRef = useRef<EventSource | null>(null);
  const mountedRef = useRef(true);

  const [messages, setMessages] = useState<SSEChatMessage[]>([]);
  const [status, setStatus] = useState<SSEChatStatus>("idle");
  const [error, setError] = useState<string | null>(null);

  // ── Cleanup ───────────────────────────────────────────────────────────────

  const cleanup = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      cleanup();
    };
  }, [cleanup]);

  // ── Send ───────────────────────────────────────────────────────────────────

  const send = useCallback(
    async (opts: SendOptions) => {
      try {
        cleanup();
        setError(null);
        setStatus("connecting");

        // Build SSE URL with query params
        const params = new URLSearchParams();
        params.append("question", opts.question);
        if (opts.jobId) params.append("job_id", opts.jobId);
        if (opts.orgId) params.append("org_id", opts.orgId);

        // Add user message to local state
        if (mountedRef.current) {
          setMessages((prev) => [...prev, { role: "user", content: opts.question }]);
          setStatus("streaming");
        }

        // Connect to SSE endpoint
        const url = `${apiClient.defaults.baseURL || "/api/v1"}/chat/sse?${params.toString()}`;
        const eventSource = new EventSource(url);
        eventSourceRef.current = eventSource;

        let assistantMessage = "";

        eventSource.addEventListener("token", (evt: Event) => {
          if (!mountedRef.current) return;
          const e = evt as MessageEvent;
          const token = e.data;
          assistantMessage += token;
          setMessages((prev) => {
            const updated = [...prev];
            const lastMsg = updated[updated.length - 1];
            if (lastMsg && lastMsg.role === "assistant") {
              lastMsg.content = assistantMessage;
              lastMsg.streaming = true;
            } else {
              updated.push({
                role: "assistant",
                content: assistantMessage,
                streaming: true,
              });
            }
            return updated;
          });
        });

        eventSource.addEventListener("done", () => {
          if (mountedRef.current) {
            setMessages((prev) => {
              const updated = [...prev];
              const lastMsg = updated[updated.length - 1];
              if (lastMsg && lastMsg.role === "assistant") {
                lastMsg.streaming = false;
              }
              return updated;
            });
            setStatus("done");
            options.onDone?.(assistantMessage);
          }
          cleanup();
        });

        eventSource.addEventListener("error", (evt: Event) => {
          if (mountedRef.current) {
            const errMsg = "SSE bağlantı hatası";
            setError(errMsg);
            setStatus("error");
            options.onError?.(errMsg);
          }
          cleanup();
        });

        // Handle standard error event
        eventSource.onerror = () => {
          if (eventSourceRef.current === eventSource) {
            if (mountedRef.current) {
              const errMsg = "SSE bağlantısı kapatıldı";
              setError(errMsg);
              setStatus("error");
              options.onError?.(errMsg);
            }
            cleanup();
          }
        };
      } catch (err) {
        if (mountedRef.current) {
          const msg = err instanceof Error ? err.message : "SSE hatası";
          setError(msg);
          setStatus("error");
          options.onError?.(msg);
        }
        cleanup();
      }
    },
    [cleanup, options]
  );

  // ── Clear ──────────────────────────────────────────────────────────────────

  const clear = useCallback(() => {
    cleanup();
    setMessages([]);
    setStatus("idle");
    setError(null);
  }, [cleanup]);

  return {
    messages,
    status,
    error,
    send,
    clear,
    /** True if currently streaming */
    isStreaming: status === "streaming" || status === "connecting",
  };
}
