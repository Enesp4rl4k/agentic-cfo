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

function fillPercent(kri: KRI): number | null {
  const { current_value, threshold_red, threshold_amber, higher_is_worse } = kri;
  if (current_value === null) return null;
  const ref = higher_is_worse ? threshold_red : threshold_amber;
  if (ref === null || ref <= 0) return null;
  const max = higher_is_worse ? ref * 1.3 : ref * 1.5;
  return Math.min(100, Math.max(0, (current_value / max) * 100));
}

function valueText(kri: KRI): string {
  return kri.current_value === null ? "—" : String(kri.current_value);
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
              {valueText(kri)} {kri.unit}
            </span>
          </div>
          {fill !== null && (
            <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
              <div
                className={cn("h-full rounded-full transition-all", barColor(kri.status))}
                style={{ width: `${fill}%` }}
              />
            </div>
          )}
        </div>
        {trend && <span className={cn("text-sm shrink-0", tColor)}>{trend}</span>}
      </div>
    );
  }

  return (
    <div className={cn("rounded-lg border p-4 space-y-3", statusBg(kri.status), className)}>
      <div className="flex items-start justify-between gap-2">
        <div className="space-y-0.5">
          <p className="font-medium text-sm leading-tight">{kri.name}</p>
          <p className="text-xs text-muted-foreground">{kri.evidence}</p>
          {kri.source && <p className="text-[11px] text-muted-foreground">Kaynak: {kri.source}</p>}
        </div>
        <div className="text-right shrink-0">
          <p className={cn("text-lg font-mono font-bold tabular-nums", statusColor(kri.status))}>
            {valueText(kri)}
            <span className="text-xs font-normal ml-0.5">{kri.unit}</span>
          </p>
          {/* One period gives no trend — say nothing rather than "stabil". */}
          {kri.trend && (
            <p className={cn("text-xs", tColor)}>
              {trend} {kri.trend === "deteriorating" ? "kötüleşiyor"
                     : kri.trend === "improving"     ? "iyileşiyor"
                     : "stabil"}
            </p>
          )}
        </div>
      </div>

      {/* Progress bar */}
      <div className="space-y-1">
        {fill !== null && (
          <div className="h-2 w-full rounded-full bg-black/20 overflow-hidden">
            <div
              className={cn("h-full rounded-full transition-all duration-500", barColor(kri.status))}
              style={{ width: `${fill}%` }}
            />
          </div>
        )}
        <div className="flex justify-between text-xs text-muted-foreground">
          <span>Amber: {kri.threshold_amber ?? "—"} {kri.unit}</span>
          <span>Kırmızı: {kri.threshold_red ?? "—"} {kri.unit}</span>
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
  kri_score:  number | null;
  className?: string;
}

export function RiskPostureBadge({
  posture, posture_tr, kri_score, className,
}: RiskPostureBadgeProps) {
  const colors: Record<string, string> = {
    critical:   "border-red-500/40 bg-red-500/15 text-red-400",
    elevated:   "border-orange-500/40 bg-orange-500/15 text-orange-400",
    stable:     "border-emerald-500/40 bg-emerald-500/15 text-emerald-400",
    no_data:    "border-border bg-muted/30 text-muted-foreground",
  };
  return (
    <div className={cn(
      "inline-flex items-center gap-2 rounded-lg border px-3 py-2",
      colors[posture] ?? colors.no_data,
      className,
    )}>
      <span className="text-lg font-mono font-bold tabular-nums">
        {kri_score === null ? "—" : `${kri_score}/10`}
      </span>
      <span className="text-sm font-semibold">{posture_tr}</span>
    </div>
  );
}
