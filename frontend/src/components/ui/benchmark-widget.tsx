"use client";

import { cn } from "@/lib/utils";
import type { BenchmarkItem, BenchmarkReport } from "@/lib/api/kernels";

// ── Percentile bar ────────────────────────────────────────────────────────────

function PercentileBar({ item }: { item: BenchmarkItem }) {
  const pct = item.percentile ?? 50;
  const barColor =
    item.higher_is_better
      ? pct >= 75 ? "bg-emerald-500" : pct >= 50 ? "bg-yellow-500" : pct >= 25 ? "bg-orange-500" : "bg-red-500"
      : pct <= 25 ? "bg-emerald-500" : pct <= 50 ? "bg-yellow-500" : pct <= 75 ? "bg-orange-500" : "bg-red-500";

  const verdictColor =
    item.higher_is_better
      ? pct >= 75 ? "text-emerald-400" : pct >= 50 ? "text-yellow-400" : "text-red-400"
      : pct <= 25 ? "text-emerald-400" : pct <= 50 ? "text-yellow-400" : "text-red-400";

  const fmt = (v: number | null) => {
    if (v === null) return "—";
    if (item.unit === "%") return `%${(v * 100).toFixed(1)}`;
    if (item.unit === "ay") return `${v.toFixed(1)} ay`;
    if (item.unit === "x") return `${v.toFixed(2)}x`;
    if (item.unit === "gün") return `${v.toFixed(0)} gün`;
    return v.toFixed(1);
  };

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium truncate">{item.metric}</span>
        <span className={cn("text-xs font-mono font-semibold shrink-0", verdictColor)}>
          {fmt(item.company_value)}
        </span>
      </div>

      {/* P25 / P50 / P75 bar */}
      <div className="relative h-4 rounded bg-muted overflow-hidden">
        {/* P25–P75 range band */}
        <div
          className="absolute top-0 h-full bg-muted-foreground/15 rounded"
          style={{ left: "25%", width: "50%" }}
        />
        {/* P50 marker */}
        <div className="absolute top-0 h-full w-px bg-muted-foreground/40" style={{ left: "50%" }} />
        {/* Company value dot */}
        {item.percentile !== null && (
          <div
            className={cn("absolute top-1 h-2 w-2 rounded-full -translate-x-1/2", barColor)}
            style={{ left: `${Math.max(4, Math.min(96, item.percentile))}%` }}
          />
        )}
      </div>

      <div className="flex items-center justify-between text-[10px] text-muted-foreground">
        <span>P25: {fmt(item.benchmark_p25)}</span>
        <span className={cn("font-medium", verdictColor)}>{item.verdict}</span>
        <span>P75: {fmt(item.benchmark_p75)}</span>
      </div>
    </div>
  );
}

// ── Main widget ───────────────────────────────────────────────────────────────

interface BenchmarkWidgetProps {
  report:   BenchmarkReport;
  loading?: boolean;
  className?: string;
}

export function BenchmarkWidget({ report, loading, className }: BenchmarkWidgetProps) {
  if (loading) {
    return (
      <div className={cn("rounded-lg border border-border bg-card p-4 space-y-3", className)}>
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="space-y-1.5 animate-pulse">
            <div className="flex justify-between">
              <div className="h-3 w-32 rounded bg-muted" />
              <div className="h-3 w-12 rounded bg-muted" />
            </div>
            <div className="h-4 rounded bg-muted" />
          </div>
        ))}
      </div>
    );
  }

  const strengths  = report.strengths  ?? [];
  const weaknesses = report.weaknesses ?? [];

  return (
    <div className={cn("rounded-lg border border-border bg-card p-4 space-y-4", className)}>
      {/* Header */}
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="font-semibold text-sm">Sektör Benchmark</p>
          <p className="text-xs text-muted-foreground capitalize">
            {report.sector} · {report.company_size}
          </p>
        </div>
        <span className="text-[10px] text-muted-foreground/60 shrink-0">
          P25 / şirket / P75
        </span>
      </div>

      {/* Metric rows */}
      <div className="space-y-3">
        {report.items.map((item) => (
          <PercentileBar key={item.metric} item={item} />
        ))}
      </div>

      {/* Summary */}
      {report.summary && (
        <p className="text-xs text-muted-foreground border-t border-border pt-3 leading-relaxed">
          {report.summary}
        </p>
      )}

      {/* Strengths / Weaknesses */}
      {(strengths.length > 0 || weaknesses.length > 0) && (
        <div className="grid grid-cols-2 gap-3 border-t border-border pt-3">
          {strengths.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-emerald-400 mb-1.5">Güçlü Yönler</p>
              <ul className="space-y-1">
                {strengths.slice(0, 3).map((s, i) => (
                  <li key={i} className="text-[11px] text-muted-foreground flex items-start gap-1">
                    <span className="text-emerald-400 mt-0.5 shrink-0">↑</span>
                    {s}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {weaknesses.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-orange-400 mb-1.5">Gelişim Alanları</p>
              <ul className="space-y-1">
                {weaknesses.slice(0, 3).map((w, i) => (
                  <li key={i} className="text-[11px] text-muted-foreground flex items-start gap-1">
                    <span className="text-orange-400 mt-0.5 shrink-0">↓</span>
                    {w}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
