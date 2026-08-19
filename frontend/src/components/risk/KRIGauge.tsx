"use client";

import { cn } from "@/lib/utils";
import type { KRI, KRIStatus } from "@/lib/api/risk";
import { statusColor, statusBg, trendIcon } from "@/lib/api/risk";

// ── Tek KRI Göstergesi ────────────────────────────────────────────────────────

interface KRIGaugeProps {
  kri:       KRI;
  compact?:  boolean;
  className?: string;
}

function fillPercent(kri: KRI): number {
  const { current_value, threshold_red, threshold_amber, higher_is_worse } = kri;
  const max = higher_is_worse ? threshold_red * 1.3 : threshold_amber * 1.5;
  const min = higher_is_worse ? 0 : 0;
  if (higher_is_worse) {
    return Math.min(100, Math.max(0, (current_value / max) * 100));
  } else {
    return Math.min(100, Math.max(0, (current_value / max) * 100));
  }
}

function barColor(status: KRIStatus): string {
  switch (status) {
    case "red":   return "bg-red-500";
    case "amber": return "bg-yellow-500";
    default:      return "bg-emerald-500";
  }
}

export function KRIGauge({ kri, compact = false, className }: KRIGaugeProps) {
  const fill    = fillPercent(kri);
  const trend   = trendIcon(kri.trend);
  const tColor  = kri.trend === "deteriorating" ? "text-red-400"
                : kri.trend === "improving"     ? "text-emerald-400"
                : "text-muted-foreground";

  if (compact) {
    return (
      <div className={cn("flex items-center gap-3", className)}>
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between mb-0.5">
            <span className="text-xs font-medium truncate">{kri.name}</span>
            <span className={cn("text-xs font-mono font-semibold shrink-0 ml-2", statusColor(kri.status))}>
              {kri.current_value} {kri.unit}
            </span>
          </div>
          <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
            <div
              className={cn("h-full rounded-full transition-all", barColor(kri.status))}
              style={{ width: `${fill}%` }}
            />
          </div>
        </div>
        <span className={cn("text-sm shrink-0", tColor)}>{trend}</span>
      </div>
    );
  }

  return (
    <div className={cn("rounded-lg border p-4 space-y-3", statusBg(kri.status), className)}>
      <div className="flex items-start justify-between gap-2">
        <div className="space-y-0.5">
          <p className="font-medium text-sm leading-tight">{kri.name}</p>
          <p className="text-xs text-muted-foreground">{kri.evidence}</p>
        </div>
        <div className="text-right shrink-0">
          <p className={cn("text-lg font-mono font-bold tabular-nums", statusColor(kri.status))}>
            {kri.current_value}
            <span className="text-xs font-normal ml-0.5">{kri.unit}</span>
          </p>
          <p className={cn("text-xs", tColor)}>
            {trend} {kri.trend === "deteriorating" ? "kötüleşiyor"
                   : kri.trend === "improving"     ? "iyileşiyor"
                   : "stabil"}
          </p>
        </div>
      </div>

      {/* Progress bar */}
      <div className="space-y-1">
        <div className="h-2 w-full rounded-full bg-black/20 overflow-hidden">
          <div
            className={cn("h-full rounded-full transition-all duration-500", barColor(kri.status))}
            style={{ width: `${fill}%` }}
          />
        </div>
        <div className="flex justify-between text-xs text-muted-foreground">
          <span>Amber: {kri.threshold_amber} {kri.unit}</span>
          <span>Red: {kri.threshold_red} {kri.unit}</span>
        </div>
      </div>

      {/* Trajectory warning */}
      {kri.trajectory_months !== null && kri.trajectory_months <= 3 && (
        <div className="text-xs text-orange-400 bg-orange-500/10 rounded px-2 py-1">
          ⚠ {kri.trajectory_months.toFixed(1)} ayda kırmızıya dönebilir
        </div>
      )}

      {/* Cascade trigger badge */}
      {kri.cascade_trigger && kri.status !== "green" && (
        <div className="text-xs text-red-400 bg-red-500/10 rounded px-2 py-1">
          ⚡ Zincirleme risk tetikleyebilir
        </div>
      )}
    </div>
  );
}

// ── KRI Listesi ───────────────────────────────────────────────────────────────

interface KRIListProps {
  kris:      KRI[];
  title?:    string;
  compact?:  boolean;
  className?: string;
}

export function KRIList({ kris, title, compact = false, className }: KRIListProps) {
  if (!kris.length) return null;
  return (
    <div className={cn("space-y-2", className)}>
      {title && (
        <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">
          {title}
        </h3>
      )}
      {kris.map((kri) => (
        <KRIGauge key={kri.name} kri={kri} compact={compact} />
      ))}
    </div>
  );
}

// ── Risk Posture Badge ────────────────────────────────────────────────────────

interface RiskPostureBadgeProps {
  posture:    string;
  posture_tr: string;
  kri_score:  number;
  className?: string;
}

export function RiskPostureBadge({
  posture, posture_tr, kri_score, className,
}: RiskPostureBadgeProps) {
  const colors: Record<string, string> = {
    critical:   "border-red-500/40 bg-red-500/15 text-red-400",
    elevated:   "border-orange-500/40 bg-orange-500/15 text-orange-400",
    moderate:   "border-yellow-500/40 bg-yellow-500/15 text-yellow-400",
    acceptable: "border-emerald-500/40 bg-emerald-500/15 text-emerald-400",
  };
  return (
    <div className={cn(
      "inline-flex items-center gap-2 rounded-lg border px-3 py-2",
      colors[posture] ?? colors.moderate,
      className,
    )}>
      <span className="text-lg font-mono font-bold tabular-nums">
        {kri_score}/10
      </span>
      <span className="text-sm font-semibold">{posture_tr}</span>
    </div>
  );
}
