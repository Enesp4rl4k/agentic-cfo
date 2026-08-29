"use client";

import Link from "next/link";
import { AlertTriangle, CheckCircle2, RefreshCw, ShieldAlert } from "lucide-react";
import { cn } from "@/lib/utils";
import type { DecisionBrief, SemanticPeriodSummary } from "@/lib/api/semantic";
import { metricSimulationHref } from "@/lib/api/semantic";

function severityClass(sev: string): string {
  switch (sev) {
    case "critical":
      return "border-red-500/40 bg-red-500/10 text-red-400";
    case "high":
      return "border-orange-500/40 bg-orange-500/10 text-orange-400";
    case "medium":
      return "border-amber-500/40 bg-amber-500/10 text-amber-400";
    default:
      return "border-border bg-muted/30 text-muted-foreground";
  }
}

function simulationHref(action?: string | null): string {
  if (!action) return "/simulation?tab=counterfactual";
  return `/simulation?tab=counterfactual&action=${encodeURIComponent(action)}`;
}

function periodHealthDelta(
  periodOptions: SemanticPeriodSummary[] | undefined,
  selectedKey: string | undefined,
): number | null {
  if (!periodOptions || periodOptions.length < 2 || !selectedKey) return null;
  const idx = periodOptions.findIndex((p) => p.period_key === selectedKey);
  if (idx < 0 || idx >= periodOptions.length - 1) return null;
  const cur = periodOptions[idx].health_score;
  const prev = periodOptions[idx + 1].health_score;
  if (cur == null || prev == null) return null;
  return cur - prev;
}

export function DecisionBriefPanel({
  brief,
  className,
  periodOptions,
  selectedPeriod,
  onPeriodChange,
  onRebuild,
  rebuilding,
  onApprove,
  approving,
}: {
  brief: DecisionBrief | null | undefined;
  className?: string;
  periodOptions?: SemanticPeriodSummary[];
  selectedPeriod?: string;
  onPeriodChange?: (periodKey: string) => void;
  onRebuild?: () => void;
  rebuilding?: boolean;
  onApprove?: () => void;
  approving?: boolean;
}) {
  const healthDelta = periodHealthDelta(periodOptions, selectedPeriod ?? brief?.period);

  if (!brief) {
    return (
      <div className={cn("rounded-lg border border-dashed border-border p-4 text-sm text-muted-foreground", className)}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p>No decision brief yet. Run a CFO analysis or rebuild the semantic model.</p>
          {onRebuild && (
            <button
              type="button"
              onClick={onRebuild}
              disabled={rebuilding}
              className="inline-flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1 text-xs hover:bg-muted disabled:opacity-50"
            >
              <RefreshCw className={cn("h-3 w-3", rebuilding && "animate-spin")} aria-hidden="true" />
              Rebuild brief
            </button>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className={cn("rounded-lg border border-primary/30 bg-card p-4 space-y-4 shadow-sm", className)}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Decision Brief · {brief.period} · {brief.currency}
          </p>
          <h2 className="mt-1 text-lg font-semibold text-foreground">{brief.headline}</h2>
          {healthDelta != null && (
            <p
              className={cn(
                "mt-1 text-xs font-medium tabular-nums",
                healthDelta >= 0 ? "text-emerald-400" : "text-red-400"
              )}
            >
              {healthDelta >= 0 ? "▲" : "▼"} {Math.abs(healthDelta)} vs prior period
            </p>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {periodOptions && periodOptions.length > 1 && onPeriodChange && (
            <select
              value={selectedPeriod ?? brief.period}
              onChange={(e) => onPeriodChange(e.target.value)}
              className="rounded-md border border-border bg-background px-2 py-1 text-xs"
              aria-label="Reporting period"
            >
              {periodOptions.map((p) => (
                <option key={p.period_key} value={p.period_key}>
                  {p.period_key}
                  {p.health_score != null ? ` (${p.health_score})` : ""}
                </option>
              ))}
            </select>
          )}
          {onRebuild && (
            <button
              type="button"
              onClick={onRebuild}
              disabled={rebuilding}
              className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs hover:bg-muted disabled:opacity-50"
              aria-label="Rebuild decision brief"
            >
              <RefreshCw className={cn("h-3 w-3", rebuilding && "animate-spin")} aria-hidden="true" />
            </button>
          )}
          <span
            className={cn(
              "rounded-md px-2.5 py-1 text-sm font-semibold tabular-nums",
              brief.health_score >= 75
                ? "bg-emerald-500/15 text-emerald-400"
                : brief.health_score >= 50
                ? "bg-amber-500/15 text-amber-400"
                : "bg-red-500/15 text-red-400"
            )}
          >
            {brief.health_score}/100
          </span>
          {brief.awaiting_review ? (
            <span className="inline-flex items-center gap-1 rounded-md border border-amber-500/40 bg-amber-500/10 px-2 py-1 text-xs text-amber-400">
              <ShieldAlert className="h-3.5 w-3.5" aria-hidden="true" />
              Awaiting review
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 rounded-md border border-emerald-500/30 bg-emerald-500/10 px-2 py-1 text-xs text-emerald-400">
              <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
              Cleared
            </span>
          )}
          {brief.awaiting_review && onApprove && (
            <button
              type="button"
              onClick={onApprove}
              disabled={approving}
              className="inline-flex items-center gap-1 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-2 py-1 text-xs font-medium text-emerald-400 hover:bg-emerald-500/20 disabled:opacity-50"
            >
              <CheckCircle2 className={cn("h-3 w-3", approving && "animate-pulse")} aria-hidden="true" />
              {approving ? "Approving…" : "Approve brief"}
            </button>
          )}
        </div>
      </div>

      <div className="space-y-2">
        <h3 className="text-xs font-medium text-muted-foreground">Findings</h3>
        <ul className="space-y-2">
          {(brief.findings || []).map((f, i) => (
            <li
              key={`${f.domain}-${i}`}
              className={cn("rounded-md border px-3 py-2 text-sm", severityClass(f.severity))}
            >
              <span className="font-medium capitalize">{f.domain}</span>
              <span className="mx-1.5 opacity-50">·</span>
              {f.statement}
              {f.metric_ids.length > 0 && (
                <span className="ml-2 inline-flex flex-wrap gap-1">
                  {f.metric_ids.map((mid) => (
                    <Link
                      key={mid}
                      href={metricSimulationHref(mid)}
                      className="rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-mono text-primary hover:underline"
                    >
                      {mid}
                    </Link>
                  ))}
                </span>
              )}
              <span className="ml-2 text-[10px] opacity-70">conf {Math.round(f.confidence * 100)}%</span>
            </li>
          ))}
        </ul>
      </div>

      {brief.recommendation && (
        <div className="rounded-md border border-primary/30 bg-primary/5 px-3 py-2">
          <p className="text-xs font-medium text-primary">Recommendation</p>
          <p className="mt-0.5 text-sm font-semibold">{brief.recommendation.title}</p>
          <p className="mt-0.5 text-xs text-muted-foreground">{brief.recommendation.rationale}</p>
        </div>
      )}

      {(brief.options || []).length > 0 && (
        <div className="space-y-1.5">
          <h3 className="text-xs font-medium text-muted-foreground">What-if options</h3>
          <ul className="grid gap-2 sm:grid-cols-3">
            {brief.options.map((o, i) => (
              <li key={i} className="rounded border border-border bg-muted/20 px-3 py-2 text-xs">
                <p className="font-medium text-foreground">{o.title}</p>
                <p className="mt-0.5 text-muted-foreground">{o.impact_summary}</p>
                <Link
                  href={simulationHref(o.linked_cf_action)}
                  className="mt-2 inline-block text-[11px] font-medium text-primary hover:underline"
                >
                  Run simulation →
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}

      {(brief.conflicts || []).length > 0 && (
        <p className="text-xs text-orange-400">
          {brief.conflicts.length} open agent conflict(s) included in this brief.
        </p>
      )}

      {brief.awaiting_review && (
        <p className="flex items-center gap-1.5 text-xs text-amber-400">
          <AlertTriangle className="h-3.5 w-3.5" aria-hidden="true" />
          Confidence gate held this brief for human review before auto-proceed.
        </p>
      )}
    </div>
  );
}
