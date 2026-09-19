"use client";

import { cn } from "@/lib/utils";
import { LottiePlayer } from "./lottie-player";
import type { AgentJobStatus, AgentJobResult } from "@/hooks/useAgentJob";

// ── Types ──────────────────────────────────────────────────────────────────────

interface AgentJobPanelProps {
  status: AgentJobStatus | null;
  progress: number;
  logs: AgentJobResult["logs"];
  error: string | null;
  agentLabel?: string;
  onReset?: () => void;
}

// ── Step label map ─────────────────────────────────────────────────────────────

const STEP_LABELS: Record<string, string> = {
  infra: "Altyapı maliyetleri", tech_debt: "Teknik borç",
  incidents: "Olay & güvenilirlik", velocity: "Geliştirici hızı",
  cto_summary: "CTO özeti", campaigns: "Kampanya performansı",
  funnel: "Lead hunisi", cohort: "Müşteri kohort",
  cmo_summary: "CMO özeti", process: "Süreç verimliliği",
  resource: "Kaynak kullanımı", sla: "SLA performansı",
  coo_summary: "COO özeti", headcount: "Headcount analizi",
  attrition: "Attrition analizi", compensation: "Ücret analizi",
  chro_summary: "CHRO özeti", register: "Risk kaydı",
  losses: "Kayıp analizi", kris: "KRI göstergeleri",
  risk_summary: "Risk özeti", findings: "Bulgular",
  controls: "Kontroller", coverage: "Denetim kapsamı",
  audit_summary: "Denetim özeti", policies: "Politikalar",
  violations: "İhlaller", regulations: "Yasal düzenlemeler",
  compliance_summary: "Uyumluluk özeti",
};

// ── Progress bar ───────────────────────────────────────────────────────────────

function ProgressBar({ progress, status }: { progress: number; status: AgentJobStatus | null }) {
  const pct = Math.max(0, Math.min(100, progress));

  const barColor =
    status === "completed" ? "bg-success" :
    status === "failed"    ? "bg-destructive" :
    "bg-primary";

  const statusText =
    status === "pending"   ? "Sıraya alındı…" :
    status === "running"   ? "Analiz yapılıyor…" :
    status === "completed" ? "Tamamlandı" :
    status === "failed"    ? "Başarısız" : "Bekleniyor";

  return (
    <div className="w-full">
      <div className="flex justify-between text-xs text-muted-foreground mb-1.5">
        <span className="transition-state">{statusText}</span>
        <span className="tabular-nums font-medium">{pct}%</span>
      </div>
      <div
        className="h-1.5 w-full overflow-hidden rounded-full bg-muted"
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="Analiz ilerleme durumu"
      >
        <div
          className={cn(
            "h-full rounded-full",
            barColor,
            // Smooth width transition — impeccable principle: meaningful only
            "transition-[width] duration-400 ease-out-expo",
            // Shimmer effect while running
            status === "running" && "animate-shimmer bg-gradient-to-r from-primary via-primary/70 to-primary bg-[length:200%_100%]"
          )}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

// ── Step list ──────────────────────────────────────────────────────────────────

function StepList({ logs }: { logs: AgentJobResult["logs"] }) {
  if (!logs || logs.length === 0) return null;

  return (
    <div className="mt-2 space-y-1">
      {logs.map((log, i) => {
        const key = log.step ?? log.node ?? `step-${i}`;
        const label = STEP_LABELS[key] ?? key;
        const ok = log.ok ?? log.status === "ok" ?? log.status === "success";
        const failed = log.status === "error" || log.status === "failed";
        const running = !ok && !failed;

        return (
          <div
            key={i}
            className={cn(
              "flex items-center gap-2 rounded px-2 py-1 text-xs",
              "transition-[background-color] duration-150 ease-out",
              ok     && "bg-success/5",
              failed && "bg-destructive/5",
              running && "bg-primary/5"
            )}
          >
            {/* Step indicator */}
            <span className="shrink-0">
              {failed ? (
                <span className="flex h-4 w-4 items-center justify-center rounded-full bg-destructive/20 text-[9px] text-destructive font-bold">✕</span>
              ) : ok ? (
                <span className="flex h-4 w-4 items-center justify-center rounded-full bg-success/20 text-[9px] text-success font-bold">✓</span>
              ) : (
                <span className="flex h-4 w-4 items-center justify-center">
                  <span className="h-3 w-3 rounded-full border-2 border-primary border-t-transparent animate-spin inline-block" />
                </span>
              )}
            </span>

            <span className={cn(
              "flex-1 transition-state",
              ok      && "text-foreground",
              failed  && "text-destructive",
              running && "text-primary",
              !ok && !failed && !running && "text-muted-foreground"
            )}>
              {label}
            </span>

            {log.detail && (
              <span className="ml-auto text-[10px] text-muted-foreground/70 truncate max-w-[120px]">
                {log.detail}
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────────────────

export function AgentJobPanel({
  status,
  progress,
  logs,
  error,
  agentLabel = "Agent",
  onReset,
}: AgentJobPanelProps) {
  const isActive = status === "pending" || status === "running";
  const isDone   = status === "completed";
  const isFailed = status === "failed";

  if (!status) return null;

  return (
    <div
      className={cn(
        "rounded-lg border p-4 space-y-3",
        "transition-[border-color,background-color] duration-300 ease-out",
        isDone   && "border-success/30 bg-success/5",
        isFailed && "border-destructive/30 bg-destructive/5",
        isActive && "border-primary/30 bg-primary/5 shadow-sm"
      )}
      role="region"
      aria-label={`${agentLabel} analiz durumu`}
    >
      {/* Header */}
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">

          {/* Lottie / CSS state indicator */}
          {isActive && (
            <LottiePlayer preset="thinking" size={24} className="shrink-0" />
          )}
          {isDone && (
            <LottiePlayer preset="success" size={24} loop={false} className="shrink-0" />
          )}
          {isFailed && (
            <LottiePlayer preset="error" size={24} loop={false} className="shrink-0" />
          )}

          <span className={cn(
            "text-sm font-medium transition-state",
            isDone   && "text-success",
            isFailed && "text-destructive",
            isActive && "text-primary"
          )}>
            {agentLabel} Analizi
          </span>
        </div>

        {(isDone || isFailed) && onReset && (
          <button
            onClick={onReset}
            className={cn(
              "text-xs text-muted-foreground hover:text-foreground",
              "underline underline-offset-2 transition-state press-feedback"
            )}
          >
            Yeni Analiz
          </button>
        )}
      </div>

      {/* Progress bar */}
      <ProgressBar progress={progress} status={status} />

      {/* Step log */}
      <StepList logs={logs} />

      {/* Error message */}
      {isFailed && error && (
        <div className="animate-slide-down rounded-md border border-destructive/30 bg-destructive/8 px-3 py-2">
          <p className="text-xs text-destructive">{error}</p>
        </div>
      )}

      {/* Success completion message */}
      {isDone && (
        <div className="animate-slide-up flex items-center gap-2 rounded-md border border-success/30 bg-success/5 px-3 py-2">
          <span className="text-xs text-success font-medium">Analiz başarıyla tamamlandı</span>
        </div>
      )}
    </div>
  );
}
