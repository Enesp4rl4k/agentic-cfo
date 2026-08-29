"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight, AlertTriangle, CheckCircle2 } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ConfidenceBreakdown as Breakdown } from "@/lib/api/muhasebe";

/**
 * "Why is confidence 0.72?" — decomposes the run's aggregate confidence into its
 * per-step components and points at the binding constraint (differentiator #6).
 */
export function ConfidenceBreakdown({ data }: { data: Breakdown | null | undefined }) {
  const [open, setOpen] = useState(false);
  if (!data) return null;

  const pct = (n: number) => `${Math.round(n * 100)}%`;
  const tone = (c: number) =>
    c >= data.threshold ? "text-emerald-400" : c >= data.threshold - 0.15 ? "text-amber-400" : "text-red-400";
  const barTone = (c: number) =>
    c >= data.threshold ? "bg-emerald-500/60" : c >= data.threshold - 0.15 ? "bg-amber-500/60" : "bg-red-500/60";

  return (
    <div className="rounded-lg border border-border bg-card/40 p-3 text-sm">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 text-left"
      >
        {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
        {data.meets_threshold ? (
          <CheckCircle2 className="h-4 w-4 text-emerald-400" />
        ) : (
          <AlertTriangle className="h-4 w-4 text-amber-400" />
        )}
        <span className="font-medium">Güven {pct(data.aggregate)}</span>
        <span className="text-xs text-muted-foreground">
          eşik {pct(data.threshold)}
          {data.binding_constraint && ` · zayıf halka: ${data.binding_constraint}`}
        </span>
      </button>

      {open && (
        <div className="mt-3 space-y-2">
          <p className="text-xs text-muted-foreground">{data.narrative}</p>
          {data.components.map((c) => (
            <div key={c.step} className="space-y-1">
              <div className="flex items-center justify-between gap-2 text-xs">
                <span className={cn("font-mono", c.weakest && "font-semibold")}>
                  {c.step}
                  {c.weakest && " ←"}
                </span>
                <span className={cn("font-mono tabular-nums", tone(c.confidence))}>
                  {pct(c.confidence)}
                </span>
              </div>
              <div className="h-1.5 overflow-hidden rounded bg-muted">
                <div
                  className={cn("h-full rounded", barTone(c.confidence))}
                  style={{ width: `${Math.max(3, c.confidence * 100)}%` }}
                />
              </div>
              {c.detail && (
                <p className="text-[11px] text-muted-foreground">{c.detail}</p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
