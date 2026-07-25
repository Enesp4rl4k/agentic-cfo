"use client";

/**
 * useAgentStream — Real-time agent progress via Server-Sent Events.
 *
 * Connects to GET /api/v1/stream/{jobId} and streams agent step events.
 *
 * Features:
 * - Auto-reconnect on network drop (up to 3 attempts)
 * - Parsed typed events (step, done, error, close)
 * - Accumulates step log for progress display
 * - Auto-closes on job completion / error
 * - Zero dependencies beyond React
 *
 * Usage:
 *   const { steps, status, currentAgent, progressPct } = useAgentStream(jobId);
 */

import { useCallback, useEffect, useRef, useState } from "react";

// ── Event types ───────────────────────────────────────────────────────────────

export type AgentStepEvent = {
  event: "step";
  job_id: string;
  step: string;
  ok: boolean;
  detail: string | null;
  confidence: number | null;
  duration_ms?: number | null;
  ts: string;
};

export type AgentDoneEvent = {
  event: "done";
  job_id: string;
  status: "completed" | "failed" | "awaiting_review";
  ts: string;
};

export type AgentErrorEvent = {
  event: "error";
  job_id: string;
  message: string;
  ts: string;
};

export type AgentStreamEvent =
  | AgentStepEvent
  | AgentDoneEvent
  | AgentErrorEvent
  | { event: "close" };

export type StreamStatus =
  | "idle"
  | "connecting"
  | "streaming"
  | "completed"
  | "failed"
  | "awaiting_review"
  | "closed"
  | "error";

// Known agent steps in execution order (for progress calculation)
const AGENT_STEPS: readonly string[] = [
  "data_ingestion",
  "pnl",
  "cashflow",
  "forecast",
  "budget",
  "tax",
  "anomaly",
  "alert",
  "report",
];

function calcProgress(completedSteps: string[]): number {
  const total = AGENT_STEPS.length;
  const done = completedSteps.filter((s) => AGENT_STEPS.includes(s)).length;
  return total > 0 ? Math.round((done / total) * 100) : 0;
}

// ── Hook ──────────────────────────────────────────────────────────────────────

export interface AgentStreamState {
  /** Ordered list of completed step events */
  steps: AgentStepEvent[];
  /** Current connection status */
  status: StreamStatus;
  /** Name of the currently running agent (null if none) */
  currentAgent: string | null;
  /** 0–100 progress estimate based on completed steps */
  progressPct: number;
  /** Final job status (set when done event received) */
  finalStatus: string | null;
  /** Error message (set when error event received) */
  errorMessage: string | null;
  /** Disconnect manually */
  disconnect: () => void;
}

export function useAgentStream(
  jobId: string | null,
  options: {
    /** Auto-start streaming when jobId is set (default: true) */
    autoConnect?: boolean;
    /** Max reconnect attempts on network drop (default: 3) */
    maxRetries?: number;
    /** Base URL for API (default: env var or localhost:8000) */
    baseUrl?: string;
  } = {}
): AgentStreamState {
  const {
    autoConnect = true,
    maxRetries = 3,
    baseUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000",
  } = options;

  const [steps, setSteps] = useState<AgentStepEvent[]>([]);
  const [status, setStatus] = useState<StreamStatus>("idle");
  const [currentAgent, setCurrentAgent] = useState<string | null>(null);
  const [progressPct, setProgressPct] = useState(0);
  const [finalStatus, setFinalStatus] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const esRef = useRef<EventSource | null>(null);
  const retriesRef = useRef(0);
  const completedStepsRef = useRef<string[]>([]);

  const disconnect = useCallback(() => {
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }
    setStatus((s) =>
      s === "streaming" || s === "connecting" ? "closed" : s
    );
  }, []);

  useEffect(() => {
    if (!jobId || !autoConnect) return;

    // Reset state on new job
    setSteps([]);
    setStatus("connecting");
    setCurrentAgent(null);
    setProgressPct(0);
    setFinalStatus(null);
    setErrorMessage(null);
    completedStepsRef.current = [];
    retriesRef.current = 0;

    function connect() {
      const url = `${baseUrl}/api/v1/stream/${jobId}`;
      const es = new EventSource(url);
      esRef.current = es;

      es.onopen = () => {
        setStatus("streaming");
        retriesRef.current = 0;
      };

      es.onmessage = (e: MessageEvent) => {
        try {
          const event = JSON.parse(e.data) as AgentStreamEvent;

          if (event.event === "step") {
            const step = event as AgentStepEvent;
            setSteps((prev) => [...prev, step]);
            setCurrentAgent(step.step);
            if (step.ok) {
              completedStepsRef.current = [
                ...completedStepsRef.current,
                step.step,
              ];
              setProgressPct(calcProgress(completedStepsRef.current));
            }
          } else if (event.event === "done") {
            const done = event as AgentDoneEvent;
            setFinalStatus(done.status);
            setStatus(
              done.status === "completed"
                ? "completed"
                : done.status === "awaiting_review"
                ? "awaiting_review"
                : "failed"
            );
            setCurrentAgent(null);
            setProgressPct(
              done.status === "completed" ? 100 : progressPct
            );
            es.close();
            esRef.current = null;
          } else if (event.event === "error") {
            const err = event as AgentErrorEvent;
            setErrorMessage(err.message);
            setStatus("error");
            es.close();
            esRef.current = null;
          } else if (event.event === "close") {
            setStatus("closed");
            es.close();
            esRef.current = null;
          }
        } catch {
          // Ignore malformed events (keepalive comments are empty)
        }
      };

      es.onerror = () => {
        es.close();
        esRef.current = null;

        // Retry on transient network errors
        if (retriesRef.current < maxRetries) {
          retriesRef.current++;
          setStatus("connecting");
          const delay = Math.min(1000 * 2 ** retriesRef.current, 10_000);
          setTimeout(connect, delay);
        } else {
          setStatus("error");
          setErrorMessage(
            "Connection lost — unable to reconnect after multiple attempts."
          );
        }
      };
    }

    connect();

    return () => {
      if (esRef.current) {
        esRef.current.close();
        esRef.current = null;
      }
    };
  }, [jobId, autoConnect, baseUrl, maxRetries]);

  return {
    steps,
    status,
    currentAgent,
    progressPct,
    finalStatus,
    errorMessage,
    disconnect,
  };
}
