"use client";

import { cn } from "@/lib/utils";

const LABELS: Record<string, string> = {
  semantic: "Semantic snapshot",
  context: "Agent context",
  job: "Analysis job",
  none: "No baseline",
};

export function BaselineSourceBadge({
  source,
  className,
}: {
  source: string | null | undefined;
  className?: string;
}) {
  const key = (source || "none").toLowerCase();
  const label = LABELS[key] ?? source ?? "Unknown";
  const isSemantic = key === "semantic";

  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md border px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide",
        isSemantic
          ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-400"
          : "border-border bg-muted/30 text-muted-foreground",
        className
      )}
      title={`Simulation baseline: ${label}`}
    >
      baseline · {label}
    </span>
  );
}
