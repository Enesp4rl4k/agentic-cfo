"use client";

/**
 * AgentProgressPanel — Real-time agent pipeline progress display.
 *
 * Shows:
 *  - Overall progress bar (0–100%)
 *  - Current running agent name
 *  - Completed steps with confidence scores and duration
 *  - Status badge (connecting / streaming / completed / failed)
 *  - Error message if pipeline fails
 *
 * Usage:
 *   <AgentProgressPanel jobId={jobId} onComplete={(status) => router.push(`/?job=${jobId}`)} />
 */

import { CheckCircle, XCircle, Loader2, Clock, AlertTriangle, Zap } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  useAgentStream,
  type AgentStepEvent,
  type StreamStatus,
} from "@/hooks/useAgentStream";

// ── Agent display metadata ─────────────────────────────────────────────────

const AGENT_META: Record<string, { label: string; description: string }> = {
  data_ingestion: { label: "Veri Okuma",      description: "CSV/Excel/PDF parse ediliyor" },
  pnl:            { label: "P&L Analizi",     description: "Gelir tablosu hesaplanıyor" },
  cashflow:       { label: "Nakit Akışı",     description: "Likidite analizi yapılıyor" },
  forecast:       { label: "Tahmin",          description: "12 aylık projeksiyon üretiliyor" },
  budget:         { label: "Bütçe",           description: "Sapma analizi yapılıyor" },
  tax:            { label: "Vergi",           description: "Vergi yükümlülükleri hesaplanıyor" },
  anomaly:        { label: "Anomali",         description: "Olağandışı işlemler taranıyor" },
  alert:          { label: "Uyarılar",        description: "Risk uyarıları oluşturuluyor" },
  report:         { label: "Rapor",           description: "Dashboard JSON hazırlanıyor" },
};

function getAgentMeta(step: string) {
  return AGENT_META[step] ?? { label: step, description: "İşleniyor…" };
}

// ── Status helpers ─────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: StreamStatus }) {
  const configs: Record<StreamStatus, { label: string; cls: string; icon: typeof Loader2 }> = {
    idle:             { label: "Bekliyor",    cls: "bg-muted text-muted-foreground",                icon: Clock    },
    connecting:       { label: "Bağlanıyor",  cls: "bg-primary/10 text-primary",                    icon: Loader2  },
    streaming:        { label: "Çalışıyor",   cls: "bg-emerald-500/10 text-emerald-500",             icon: Loader2  },
    completed:        { label: "Tamamlandı",  cls: "bg-emerald-500/10 text-emerald-500",             icon: CheckCircle },
    failed:           { label: "Başarısız",   cls: "bg-destructive/10 text-destructive",             icon: XCircle  },
    awaiting_review:  { label: "İnceleme",    cls: "bg-amber-500/10 text-amber-500",                 icon: AlertTriangle },
    closed:           { label: "Kapatıldı",   cls: "bg-muted text-muted-foreground",                 icon: Clock    },
    error:            { label: "Bağlantı Hatası", cls: "bg-destructive/10 text-destructive",         icon: XCircle  },
  };

  const cfg = configs[status] ?? configs.idle;
  const Icon = cfg.icon;
  const isSpinning = status === "connecting" || status === "streaming";

  return (
    <span className={cn(
      "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium",
      cfg.cls
    )}>
      <Icon className={cn("h-3 w-3", isSpinning && "animate-spin")} aria-hidden="true" />
      {cfg.label}
    </span>
  );
}

// ── Step row ──────────────────────────────────────────────────────────────

function StepRow({ step }: { step: AgentStepEvent }) {
  const meta = getAgentMeta(step.step);
  return (
    <div className={cn(
      "flex items-start gap-3 rounded-md px-3 py-2.5 text-sm transition-colors",
      step.ok ? "bg-emerald-500/5" : "bg-destructive/5"
    )}>
      {step.ok
        ? <CheckCircle className="mt-0.5 h-4 w-4 shrink-0 text-emerald-500" aria-hidden="true" />
        : <XCircle    className="mt-0.5 h-4 w-4 shrink-0 text-destructive"  aria-hidden="true" />
      }
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="font-medium">{meta.label}</span>
          {step.confidence != null && (
            <span className="text-xs text-muted-foreground tabular-nums">
              {(step.confidence * 100).toFixed(0)}% güven
            </span>
          )}
        </div>
        {step.detail && (
          <p className="mt-0.5 text-xs text-muted-foreground truncate max-w-[320px]">
            {step.detail}
          </p>
        )}
      </div>
      <span className="shrink-0 text-xs text-muted-foreground tabular-nums">
        {new Date(step.ts).toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
      </span>
    </div>
  );
}

// ── Active agent indicator ────────────────────────────────────────────────

function ActiveAgentRow({ agentName }: { agentName: string }) {
  const meta = getAgentMeta(agentName);
  return (
    <div className="flex items-center gap-3 rounded-md border border-primary/20 bg-primary/5 px-3 py-2.5">
      <Loader2 className="h-4 w-4 shrink-0 animate-spin text-primary" aria-hidden="true" />
      <div className="flex-1 min-w-0">
        <span className="text-sm font-medium text-primary">{meta.label}</span>
        <p className="text-xs text-muted-foreground">{meta.description}</p>
      </div>
      <span className="text-xs text-primary">şu an</span>
    </div>
  );
}

// ── Progress bar ──────────────────────────────────────────────────────────

function ProgressBar({ pct, status }: { pct: number; status: StreamStatus }) {
  const isActive = status === "streaming" || status === "connecting";
  const isFailed = status === "failed" || status === "error";

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-xs">
        <span className="text-muted-foreground">İlerleme</span>
        <span className={cn(
          "tabular-nums font-medium",
          isFailed ? "text-destructive" : "text-foreground"
        )}>
          {pct}%
        </span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
        <div
          className={cn(
            "h-full rounded-full transition-all duration-500 ease-out",
            isFailed         ? "bg-destructive" :
            status === "completed" ? "bg-emerald-500" :
            "bg-primary"
          )}
          style={{ width: `${pct}%` }}
          role="progressbar"
          aria-valuenow={pct}
          aria-valuemin={0}
          aria-valuemax={100}
        />
      </div>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────

interface AgentProgressPanelProps {
  jobId: string | null;
  /** Called when pipeline completes (completed | failed | awaiting_review) */
  onComplete?: (status: string) => void;
  /** Show compact version without step log */
  compact?: boolean;
  className?: string;
}

export function AgentProgressPanel({
  jobId,
  onComplete,
  compact = false,
  className,
}: AgentProgressPanelProps) {
  const { steps, status, currentAgent, progressPct, errorMessage } =
    useAgentStream(jobId, { autoConnect: !!jobId });

  // Notify parent on completion
  const doneStatuses: StreamStatus[] = ["completed", "failed", "awaiting_review"];
  const isDone = doneStatuses.includes(status);

  // Call onComplete once when done
  const calledRef = { current: false };
  if (isDone && !calledRef.current && onComplete) {
    calledRef.current = true;
    // Defer to avoid calling during render
    setTimeout(() => onComplete(status), 0);
  }

  if (!jobId) return null;

  return (
    <div className={cn("rounded-lg border border-border bg-card p-4 space-y-4", className)}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Zap className="h-4 w-4 text-primary" aria-hidden="true" />
          <h3 className="text-sm font-semibold">AI Agent Pipeline</h3>
        </div>
        <StatusBadge status={status} />
      </div>

      {/* Progress bar */}
      <ProgressBar pct={progressPct} status={status} />

      {/* Error message */}
      {errorMessage && (
        <div
          role="alert"
          className="flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/8 px-3 py-2 text-xs text-destructive"
        >
          <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          <span>{errorMessage}</span>
        </div>
      )}

      {/* Active agent */}
      {currentAgent && status === "streaming" && (
        <ActiveAgentRow agentName={currentAgent} />
      )}

      {/* Step log — hidden in compact mode */}
      {!compact && steps.length > 0 && (
        <div className="space-y-1.5">
          <p className="text-xs font-medium text-muted-foreground">Tamamlanan Adımlar</p>
          <div className="space-y-1 max-h-64 overflow-y-auto pr-0.5">
            {[...steps].reverse().map((step, i) => (
              <StepRow key={`${step.step}-${i}`} step={step} />
            ))}
          </div>
        </div>
      )}

      {/* Compact: just step count */}
      {compact && steps.length > 0 && (
        <p className="text-xs text-muted-foreground">
          {steps.length} adım tamamlandı
        </p>
      )}
    </div>
  );
}
