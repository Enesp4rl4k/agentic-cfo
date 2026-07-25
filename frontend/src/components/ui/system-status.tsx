"use client";

/**
 * SystemStatusWidget — Real-time system health display.
 *
 * Shows:
 *  - API connection status (online / offline)
 *  - Active analysis jobs count
 *  - Agent pipeline uptime
 *  - Quick link to API docs
 *
 * Polls /health every 30s and /jobs every 15s.
 */

import { useEffect, useState } from "react";
import { Activity, CheckCircle2, XCircle, Loader2, ExternalLink } from "lucide-react";
import { cn } from "@/lib/utils";
import { apiClient } from "@/lib/api/client";
import { useJobs } from "@/hooks/useCFO";

type ApiStatus = "checking" | "online" | "offline";

function useApiHealth(intervalMs = 30_000) {
  const [status, setStatus] = useState<ApiStatus>("checking");
  const [latencyMs, setLatencyMs] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function check() {
      const t0 = performance.now();
      try {
        await apiClient.get("/../../health", { timeout: 5_000 });
        const lat = Math.round(performance.now() - t0);
        if (!cancelled) {
          setStatus("online");
          setLatencyMs(lat);
        }
      } catch {
        if (!cancelled) {
          setStatus("offline");
          setLatencyMs(null);
        }
      }
    }

    check();
    const id = setInterval(check, intervalMs);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [intervalMs]);

  return { status, latencyMs };
}

// ── Dot indicator ──────────────────────────────────────────────────────────

function StatusDot({ status }: { status: ApiStatus }) {
  return (
    <span
      className={cn(
        "inline-block h-2 w-2 rounded-full",
        status === "online"   ? "bg-emerald-500"       :
        status === "offline"  ? "bg-destructive"        :
        "bg-amber-500 animate-pulse"
      )}
      aria-hidden="true"
    />
  );
}

// ── Main component ─────────────────────────────────────────────────────────

interface SystemStatusWidgetProps {
  /** Show full panel (default) or minimal inline badge */
  variant?: "panel" | "inline";
  className?: string;
}

export function SystemStatusWidget({
  variant = "panel",
  className,
}: SystemStatusWidgetProps) {
  const { status: apiStatus, latencyMs } = useApiHealth();
  const { data: jobs } = useJobs();

  const activeJobs = jobs?.filter((j) =>
    ["pending", "ingesting", "analyzing"].includes(j.status)
  ).length ?? 0;

  const completedToday = jobs?.filter((j) => {
    if (!j.completed_at) return false;
    const today = new Date().toDateString();
    return new Date(j.completed_at).toDateString() === today;
  }).length ?? 0;

  // ── Inline variant ─────────────────────────────────────────────────────
  if (variant === "inline") {
    return (
      <div className={cn("flex items-center gap-1.5 text-xs text-muted-foreground", className)}>
        <StatusDot status={apiStatus} />
        <span>
          {apiStatus === "online"  ? "Online" :
           apiStatus === "offline" ? "Offline" :
           "Checking…"}
        </span>
        {activeJobs > 0 && (
          <>
            <span className="text-border">·</span>
            <Activity className="h-3 w-3 text-primary animate-pulse" aria-hidden="true" />
            <span className="text-primary">{activeJobs} aktif</span>
          </>
        )}
      </div>
    );
  }

  // ── Panel variant ──────────────────────────────────────────────────────
  return (
    <div className={cn("rounded-lg border border-border bg-card p-4", className)}>
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Activity className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
          <h3 className="text-sm font-semibold">Sistem Durumu</h3>
        </div>
        <a
          href={`${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/docs`}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
          aria-label="Open API documentation"
        >
          API Docs
          <ExternalLink className="h-3 w-3" aria-hidden="true" />
        </a>
      </div>

      <div className="space-y-2">
        {/* API status */}
        <div className="flex items-center justify-between rounded-md bg-muted/30 px-3 py-2">
          <div className="flex items-center gap-2">
            {apiStatus === "online" ? (
              <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" aria-hidden="true" />
            ) : apiStatus === "offline" ? (
              <XCircle className="h-3.5 w-3.5 text-destructive" aria-hidden="true" />
            ) : (
              <Loader2 className="h-3.5 w-3.5 animate-spin text-amber-500" aria-hidden="true" />
            )}
            <span className="text-xs font-medium">Backend API</span>
          </div>
          <div className="flex items-center gap-2">
            <StatusDot status={apiStatus} />
            <span className="text-xs text-muted-foreground">
              {apiStatus === "online"  ? (latencyMs ? `${latencyMs}ms` : "Online") :
               apiStatus === "offline" ? "Offline" :
               "Kontrol ediliyor…"}
            </span>
          </div>
        </div>

        {/* Active jobs */}
        <div className="flex items-center justify-between rounded-md bg-muted/30 px-3 py-2">
          <div className="flex items-center gap-2">
            <Activity
              className={cn("h-3.5 w-3.5", activeJobs > 0 ? "text-primary animate-pulse" : "text-muted-foreground")}
              aria-hidden="true"
            />
            <span className="text-xs font-medium">Aktif Analizler</span>
          </div>
          <span className={cn(
            "text-xs font-semibold tabular-nums",
            activeJobs > 0 ? "text-primary" : "text-muted-foreground"
          )}>
            {activeJobs}
          </span>
        </div>

        {/* Completed today */}
        <div className="flex items-center justify-between rounded-md bg-muted/30 px-3 py-2">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
            <span className="text-xs font-medium">Bugün Tamamlanan</span>
          </div>
          <span className="text-xs tabular-nums text-muted-foreground">
            {completedToday}
          </span>
        </div>
      </div>

      {/* Footer */}
      <p className="mt-3 text-[10px] text-muted-foreground/60">
        Her 30 saniyede bir güncellenir
      </p>
    </div>
  );
}
