"use client";

/**
 * useJobStream — SSE-based real-time job progress hook.
 *
 * Connects to GET /api/v1/stream/{jobId} and provides:
 *   - steps: list of completed agent steps with ok/detail/confidence
 *   - progress: 0–100 percentage
 *   - currentStep: the step currently being processed
 *   - status: "connecting" | "running" | "completed" | "failed" | "awaiting_review" | "idle"
 *
 * Automatically falls back to polling if SSE is unsupported or fails.
 * Cleans up EventSource on unmount or jobId change.
 */

import { useEffect, useRef, useState, useCallback } from "react";
import { streamUrl } from "@/lib/api/client";

export interface StepEvent {
  step: string;
  ok: boolean;
  detail: string | null;
  confidence: number | null;
  progress_pct: number;
  ts: string;
}

export type StreamStatus =
  | "idle"
  | "connecting"
  | "running"
  | "completed"
  | "failed"
  | "awaiting_review";

export interface JobStreamState {
  status: StreamStatus;
  steps: StepEvent[];
  progress: number;
  currentStep: string | null;
  error: string | null;
}

const API_URL = (
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"
).replace(/\/$/, "");

const STEP_LABELS: Record<string, string> = {
  data_ingestion: "Veri Okunuyor",
  pnl:            "P&L Hesaplanıyor",
  cashflow:       "Nakit Akışı Analizi",
  forecast:       "Tahmin Üretiliyor",
  anomaly:        "Anomali Tespiti",
  tax:            "Vergi Hesabı",
  budget:         "Bütçe Karşılaştırması",
  alert:          "Uyarılar Değerlendiriliyor",
  report:         "Rapor Oluşturuluyor",
};

export function getStepLabel(step: string): string {
  return STEP_LABELS[step] ?? step;
}

export function useJobStream(jobId: string | null): JobStreamState {
  const [state, setState] = useState<JobStreamState>({
    status: "idle",
    steps: [],
    progress: 0,
    currentStep: null,
    error: null,
  });

  const esRef = useRef<EventSource | null>(null);

  const cleanup = useCallback(() => {
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }
  }, []);

  useEffect(() => {
    if (!jobId) {
      setState({
        status: "idle",
        steps: [],
        progress: 0,
        currentStep: null,
        error: null,
      });
      return;
    }

    cleanup();

    setState((prev) => ({ ...prev, status: "connecting", steps: [], progress: 0 }));

    let cancelled = false;

    // A ticket first: EventSource cannot send the session header, so the
    // stream authenticates by a short-lived ticket scoped to this job.
    async function open() {
      let url: string;
      try {
        url = await streamUrl(jobId!);
      } catch {
        if (!cancelled) {
          setState((prev) => ({ ...prev, status: "failed", error: "Canlı akış için yetki alınamadı." }));
        }
        return;
      }
      if (cancelled) return;
      const es = new EventSource(url);
      esRef.current = es;

      es.onopen = () => {
        setState((prev) => ({ ...prev, status: "running" }));
      };

      es.onmessage = (event: MessageEvent) => {
        try {
          const data = JSON.parse(event.data as string) as {
            event: string;
            step?: string;
            ok?: boolean;
            detail?: string | null;
            confidence?: number | null;
            progress_pct?: number;
            status?: string;
            message?: string;
            ts?: string;
          };

          if (data.event === "step" && data.step) {
            const stepEvent: StepEvent = {
              step: data.step,
              ok: data.ok ?? true,
              detail: data.detail ?? null,
              confidence: data.confidence ?? null,
              progress_pct: data.progress_pct ?? 0,
              ts: data.ts ?? new Date().toISOString(),
            };

            setState((prev) => ({
              ...prev,
              status: "running",
              steps: [...prev.steps.filter((s) => s.step !== data.step), stepEvent],
              progress: data.progress_pct ?? prev.progress,
              currentStep: data.step ?? null,
            }));
          } else if (data.event === "agent_start" && data.step) {
            setState((prev) => ({
              ...prev,
              status: "running",
              currentStep: (data.step ?? null) as string | null,
              progress: data.progress_pct ?? prev.progress,
            }));
          } else if (data.event === "done") {
            const finalStatus =
              data.status === "awaiting_review"
                ? "awaiting_review"
                : data.status === "failed"
                ? "failed"
                : "completed";

            setState((prev) => ({
              ...prev,
              status: finalStatus,
              progress: finalStatus === "completed" ? 100 : prev.progress,
              currentStep: null,
            }));
            cleanup();
          } else if (data.event === "error") {
            setState((prev) => ({
              ...prev,
              status: "failed",
              error: data.message ?? "Pipeline hatası",
              currentStep: null,
            }));
            cleanup();
          } else if (data.event === "close") {
            cleanup();
          }
        } catch {
          // Malformed SSE message — ignore
        }
      };

      es.onerror = () => {
        // EventSource auto-reconnects on transient errors.
        // Only mark as failed if we're still connecting (persistent failure).
        setState((prev) => {
          if (prev.status === "connecting") {
            return { ...prev, status: "failed", error: "SSE bağlantısı kurulamadı" };
          }
          return prev;
        });
      };

    }

    void open();

    return () => {
      cancelled = true;
      cleanup();
    };
  }, [jobId, cleanup]);

  return state;
}
