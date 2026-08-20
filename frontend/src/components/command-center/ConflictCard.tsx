"use client";

import { AlertTriangle, CheckCircle2, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { useConflicts, useResolveConflict, useRunConsensus } from "@/hooks/useConflicts";

const SEVERITY_CLASS: Record<string, string> = {
  critical: "border-red-500/40 bg-red-500/10 text-red-200",
  high: "border-amber-500/40 bg-amber-500/10 text-amber-200",
  medium: "border-yellow-500/30 bg-yellow-500/10 text-yellow-100",
  low: "border-border bg-muted/20 text-muted-foreground",
};

export function ConflictCard() {
  const { data, isLoading, isError } = useConflicts();
  const resolveMut = useResolveConflict();
  const consensusMut = useRunConsensus();

  const conflicts = data?.conflicts ?? [];
  const openCount = conflicts.filter((c) => c.status === "open").length;

  return (
    <div className="rounded-lg border border-border bg-card p-5">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <AlertTriangle className="h-4 w-4 text-amber-400" aria-hidden="true" />
          <h2 className="text-sm font-semibold">Agent Conflicts</h2>
        </div>
        <span className="rounded border border-border px-2 py-0.5 text-xs text-muted-foreground">
          {openCount} open
        </span>
      </div>

      <div className="mb-3 flex flex-wrap gap-2">
        {["cash_risk", "revenue_outlook"].map((topic) => (
          <button
            key={topic}
            type="button"
            disabled={consensusMut.isPending}
            onClick={() => consensusMut.mutate(topic)}
            className="rounded border border-border bg-muted/20 px-2 py-1 text-[11px] text-muted-foreground hover:bg-muted/40 disabled:opacity-50"
          >
            Run {topic}
          </button>
        ))}
      </div>

      {isLoading ? (
        <p className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="h-3 w-3 animate-spin" /> Loading conflicts…
        </p>
      ) : isError ? (
        <p className="rounded border border-border bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
          Conflicts unavailable (table or org scope may be missing).
        </p>
      ) : conflicts.length === 0 ? (
        <p className="rounded border border-border bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
          No agent conflicts detected. Consensus is stable.
        </p>
      ) : (
        <div className="space-y-2">
          {conflicts.slice(0, 5).map((c) => {
            const severity = c.severity || "medium";
            return (
              <div
                key={c.id}
                className={cn("rounded border px-3 py-2", SEVERITY_CLASS[severity] || SEVERITY_CLASS.low)}
              >
                <div className="mb-1 flex items-center justify-between gap-2">
                  <p className="text-xs font-medium">{c.topic}</p>
                  <span className="text-[10px] uppercase opacity-80">{severity}</span>
                </div>
                <p className="text-[11px] opacity-90">
                  score: {c.consensus_score != null ? c.consensus_score.toFixed(2) : "n/a"} · status: {c.status}
                </p>
                {c.status === "open" && (
                  <button
                    type="button"
                    disabled={resolveMut.isPending}
                    onClick={() =>
                      resolveMut.mutate({
                        conflictId: c.id,
                        resolution: "accept_consensus",
                        note: "Resolved from Command Center",
                      })
                    }
                    className="mt-2 inline-flex items-center gap-1 rounded border border-current/30 px-2 py-1 text-[11px] hover:bg-black/10 disabled:opacity-50"
                  >
                    <CheckCircle2 className="h-3 w-3" />
                    Resolve
                  </button>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
